"""
model.py
--------
Modelo basado en agentes para control de congestion en una red de 50 nodos.
Curso: Sistemas Complejos - Examen Parcial.

Este archivo intenta usar el framework Mesa (mesa.Agent, mesa.Model,
mesa.time.RandomActivation). Si Mesa no esta instalado en el entorno donde
se ejecuta (por ejemplo, para pruebas rapidas sin dependencias), se usa un
"shim" interno con la misma interfaz minima, de modo que el codigo de la
simulacion (que es lo que realmente importa para el parcial) es identico
en ambos casos.

Para el entregable final, instale Mesa con:
    pip install "mesa<3.0"
(se usa la API clasica Agent(unique_id, model) + mesa.time.RandomActivation,
disponible en Mesa 1.x y 2.x).
"""

import random
import itertools
import networkx as nx

# ---------------------------------------------------------------------------
# Compatibilidad con Mesa
# ---------------------------------------------------------------------------
try:
    from mesa import Agent as MesaAgent, Model as MesaModel
    from mesa.time import RandomActivation
    MESA_AVAILABLE = True
except ImportError:
    MESA_AVAILABLE = False

    class MesaAgent:
        def __init__(self, unique_id, model):
            self.unique_id = unique_id
            self.model = model

    class MesaModel:
        def __init__(self):
            self.running = True

    class RandomActivation:
        """Shim minimo compatible con mesa.time.RandomActivation."""
        def __init__(self, model):
            self.model = model
            self._agents = {}

        def add(self, agent):
            self._agents[agent.unique_id] = agent

        def step(self):
            agents = list(self._agents.values())
            random.shuffle(agents)
            for a in agents:
                a.step()

        def get_agent_count(self):
            return len(self._agents)


# ---------------------------------------------------------------------------
# Paquete de datos
# ---------------------------------------------------------------------------
class Packet:
    """Representa un mensaje/paquete 'm' que viaja entre agentes (alpha<->beta)."""
    _id_counter = itertools.count()

    def __init__(self, source, dest, created_step):
        self.id = next(Packet._id_counter)
        self.source = source
        self.dest = dest
        self.created_step = created_step
        self.hops = 0

    def __repr__(self):
        return f"Packet({self.id}: {self.source}->{self.dest}, hops={self.hops})"


# ---------------------------------------------------------------------------
# Agente: nodo de la red
# ---------------------------------------------------------------------------
class NetworkNodeAgent(MesaAgent):
    """
    Un nodo de comunicacion (agente alpha).

    Estado: cola finita de paquetes, tasa de generacion actual, estado de
    congestion propio, y memoria de vecinos que han senalado congestion
    (informacion de control recibida m = 'CONGESTIONADO').

    Percepcion: ocupacion de su propia cola + senales de congestion de vecinos.
    Accion: generar, reenviar, retener (backpressure) o desviar paquetes;
    regular (throttle) su propia tasa de generacion.
    """

    def __init__(self, unique_id, model):
        if MESA_AVAILABLE:
            super().__init__(unique_id, model)
        else:
            super().__init__(unique_id, model)

        self.queue = []                       # cola FIFO de Packet
        self.neighbors = []                   # se llena luego de construir la red
        self.base_gen_rate = model.base_gen_rate
        self.current_gen_rate = model.base_gen_rate
        self.status = "normal"                # normal | warning | critical
        self.occupancy = 0.0
        # vecinos que han señalado congestion critica -> steps de cooldown restantes
        self.congested_neighbors = {}
        # contadores locales (para depuracion / analisis por nodo, opcional)
        self.generated = 0
        self.dropped_full_queue = 0
        self.dropped_ttl = 0

    # -- fase 1: generacion de trafico -------------------------------------
    def generate_phase(self):
        rate = self.current_gen_rate if self.model.control_enabled else self.base_gen_rate
        if self.model.random.random() < rate:
            dest = self.model.pick_destination(self.unique_id)
            if dest is not None:
                pkt = Packet(self.unique_id, dest, self.model.steps)
                if len(self.queue) < self.model.max_queue_size:
                    self.queue.append(pkt)
                    self.generated += 1
                    self.model.stats["generated"] += 1
                else:
                    # la cola de origen ya esta llena: el paquete ni siquiera
                    # se admite a la red (control de admision, no se "elimina"
                    # trafico que ya viaja por la red).
                    self.model.stats["rejected_at_admission"] += 1

    # -- regla local de enrutamiento (siguiente salto) -----------------------
    def get_next_hop(self, pkt):
        primary = self.model.next_hop_table[self.unique_id].get(pkt.dest)
        if primary is None:
            return None

        if self.model.control_enabled and primary in self.congested_neighbors:
            # Regla de control: si el salto primario esta marcado como
            # congestionado por una senal reciente, se busca un vecino
            # alternativo que no aumente demasiado la distancia al destino
            # (desvio acotado). Si no hay alternativa razonable, se conserva
            # el salto primario (esto produce backpressure: el paquete
            # espera en la cola en vez de forzar el envio).
            dist = self.model.dist_matrix
            alt_candidates = [
                n for n in self.neighbors
                if n not in self.congested_neighbors and n in dist and pkt.dest in dist[n]
            ]
            if alt_candidates:
                best = min(alt_candidates, key=lambda n: dist[n][pkt.dest])
                primary_dist = dist[primary].get(pkt.dest, float("inf"))
                if dist[best][pkt.dest] <= primary_dist + self.model.detour_slack:
                    return best
        return primary

    # -- fase de control: throttling AIMD + limpieza de senales -------------
    def control_phase(self):
        if not self.model.control_enabled:
            self.current_gen_rate = self.base_gen_rate
        else:
            if self.status in ("warning", "critical"):
                # decremento multiplicativo (AIMD: "M" de multiplicative decrease)
                self.current_gen_rate = max(
                    self.model.min_gen_rate, self.current_gen_rate * self.model.aimd_decrease
                )
            else:
                # incremento aditivo (AIMD: "A" de additive increase)
                self.current_gen_rate = min(
                    self.base_gen_rate, self.current_gen_rate + self.model.aimd_increase
                )

        # cooldown de las senales de congestion recibidas de vecinos
        expired = [n for n, t in self.congested_neighbors.items() if t <= 1]
        for n in expired:
            del self.congested_neighbors[n]
        for n in self.congested_neighbors:
            self.congested_neighbors[n] -= 1

    # -- actualizar estado de congestion propio a partir de la ocupacion ----
    def update_status(self):
        self.occupancy = len(self.queue) / self.model.max_queue_size
        if self.occupancy >= self.model.threshold_critical:
            self.status = "critical"
        elif self.occupancy >= self.model.threshold_warning:
            self.status = "warning"
        else:
            self.status = "normal"

    def step(self):
        # El grueso de la logica de transmision se coordina de forma
        # centralizada en el modelo (para resolver correctamente la
        # competencia por la capacidad de cada enlace en un mismo paso).
        self.generate_phase()


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
class NetworkCongestionModel(MesaModel):
    """
    Red N de 50 nodos (agentes) con enlaces de capacidad finita, colas
    finitas, enrutamiento por tabla de siguiente-salto y control
    distribuido de congestion opcional.
    """

    def __init__(
        self,
        num_nodes=50,
        k=4,                       # grado inicial del anillo (ring lattice)
        p_rewire=0.12,             # prob. de enlaces adicionales (NW small-world)
        edge_capacity=1,           # paquetes/paso que soporta cada enlace (por direccion)
        max_queue_size=10,         # tamano maximo de la cola de cada nodo
        base_gen_rate=0.25,        # prob. de generar paquete por paso y por nodo
        control_enabled=True,
        threshold_warning=0.5,
        threshold_critical=0.8,
        aimd_decrease=0.5,
        aimd_increase=0.02,
        min_gen_rate=0.0,
        detour_slack=2,
        n_hotspots=3,               # nodos "gateway" que reciben trafico desproporcionado
        hotspot_bias=0.55,          # prob. de que el destino sea un hotspot
        seed=42,
    ):
        super().__init__()
        self.random = random.Random(seed)
        self.seed_value = seed
        self.num_nodes = num_nodes
        self.edge_capacity = edge_capacity
        self.max_queue_size = max_queue_size
        self.base_gen_rate = base_gen_rate
        self.control_enabled = control_enabled
        self.threshold_warning = threshold_warning
        self.threshold_critical = threshold_critical
        self.aimd_decrease = aimd_decrease
        self.aimd_increase = aimd_increase
        self.min_gen_rate = min_gen_rate
        self.detour_slack = detour_slack
        self.n_hotspots = n_hotspots
        self.hotspot_bias = hotspot_bias
        self.steps = 0

        # ---- Topologia: anillo con enlaces adicionales (Newman-Watts) ----
        # Conectada por construccion (contiene el anillo base) y con
        # heterogeneidad local (algunos nodos con mas vecinos), lo que
        # favorece la aparicion de puntos de congestion no triviales.
        self.G = nx.newman_watts_strogatz_graph(num_nodes, k, p_rewire, seed=seed)
        assert nx.is_connected(self.G), "La topologia generada no es conexa"

        # ---- Tabla de enrutamiento (siguiente salto) por nodo -------------
        # Se precomputa una vez (equivalente a un protocolo de vector de
        # estado tipo link-state ya convergido); cada agente solo consulta
        # su propia fila, que es la unica informacion de enrutamiento que
        # usa en tiempo de simulacion.
        self.next_hop_table = {}
        self.dist_matrix = {}
        for s in self.G.nodes:
            paths = nx.single_source_shortest_path(self.G, s)
            lengths = nx.single_source_shortest_path_length(self.G, s)
            self.next_hop_table[s] = {
                t: (path[1] if len(path) > 1 else None) for t, path in paths.items()
            }
            self.dist_matrix[s] = dict(lengths)

        diameter = nx.diameter(self.G)
        self.max_hops = diameter + 2 * detour_slack + 4  # TTL para evitar bucles

        # ---- Patron de trafico: unos pocos nodos "gateway"/hotspot reciben ----
        # una fraccion desproporcionada del trafico (p. ej. servidores o
        # salidas a internet). Esto genera puntos de convergencia de flujo
        # realistas donde es mas probable observar congestion persistente,
        # en vez de que la carga se diluya uniformemente en toda la red.
        self.hotspots = self.random.sample(list(self.G.nodes), min(n_hotspots, num_nodes))

        # ---- Agentes ----
        self.schedule = RandomActivation(self)
        self.agents_by_id = {}
        for node_id in self.G.nodes:
            a = NetworkNodeAgent(node_id, self)
            self.schedule.add(a)
            self.agents_by_id[node_id] = a
        for node_id in self.G.nodes:
            self.agents_by_id[node_id].neighbors = list(self.G.neighbors(node_id))

        # ---- estadisticas agregadas ----
        self.stats = {
            "generated": 0,
            "delivered": 0,
            "dropped_queue_full": 0,
            "dropped_ttl": 0,
            "rejected_at_admission": 0,
        }
        self.latencies = []

        # historial por paso (para series de tiempo / analisis)
        self.history = {
            "step": [],
            "throughput": [],
            "mean_queue": [],
            "max_queue": [],
            "prop_congested_edges": [],
            "prop_congested_nodes": [],
            "delivered_cum": [],
            "dropped_cum": [],
            "generated_cum": [],
            "mean_gen_rate": [],
        }

        self._congested_signal_prev = set()  # nodos que fueron 'critical' en el paso anterior

    # -- destino aleatorio distinto del origen -------------------------------
    def pick_destination(self, source_id):
        if self.hotspots and self.random.random() < self.hotspot_bias:
            candidates = [h for h in self.hotspots if h != source_id]
            if candidates:
                return self.random.choice(candidates)
        dest = self.random.randrange(self.num_nodes)
        tries = 0
        while dest == source_id and tries < 5:
            dest = self.random.randrange(self.num_nodes)
            tries += 1
        return dest if dest != source_id else None

    # -- un paso de simulacion ------------------------------------------------
    def step(self):
        self.steps += 1
        edges_used_this_step = 0
        edges_over_capacity = 0
        delivered_this_step = 0

        # 1) fase de generacion (orden aleatorio de agentes)
        self.schedule.step()

        # 2) construir solicitudes de transmision por arista dirigida
        #    (respetando el orden FIFO de cada cola)
        desired = {}  # (u, v) -> lista de (agente_origen, paquete)
        # tomamos una "foto" para poder decidir next_hop de forma consistente
        for node_id, agent in self.agents_by_id.items():
            for pkt in agent.queue:
                nh = agent.get_next_hop(pkt)
                if nh is None:
                    continue
                desired.setdefault((node_id, nh), []).append(pkt)

        # 3) resolver capacidad de cada enlace dirigido (u->v)
        already_sent = set()  # ids de paquetes ya procesados en este paso
        for (u, v), pkts in desired.items():
            edges_used_this_step += 1
            cap = self.edge_capacity
            to_send = [p for p in pkts if p.id not in already_sent][:cap]
            if len(pkts) > cap:
                edges_over_capacity += 1

            v_agent = self.agents_by_id[v]
            u_agent = self.agents_by_id[u]
            for pkt in to_send:
                already_sent.add(pkt.id)
                # se retira de la cola de origen (se consumio capacidad del enlace)
                try:
                    u_agent.queue.remove(pkt)
                except ValueError:
                    continue
                pkt.hops += 1

                if pkt.hops > self.max_hops:
                    self.stats["dropped_ttl"] += 1
                    u_agent.dropped_ttl += 1
                    continue

                if v == pkt.dest:
                    delivered_this_step += 1
                    self.stats["delivered"] += 1
                    self.latencies.append(self.steps - pkt.created_step)
                    continue

                # intento de encolar en el nodo receptor (cola finita -> drop-tail)
                if len(v_agent.queue) < self.max_queue_size:
                    v_agent.queue.append(pkt)
                else:
                    self.stats["dropped_queue_full"] += 1
                    v_agent.dropped_full_queue += 1

        # 4) actualizar estado de congestion (ocupacion de cola) por nodo
        for agent in self.agents_by_id.values():
            agent.update_status()

        congested_nodes_now = {
            nid for nid, a in self.agents_by_id.items() if a.status == "critical"
        }

        # 5) propagar senal de congestion a los vecinos (con 1 paso de
        #    retardo, como corresponde a un sistema distribuido real) y
        #    ejecutar la fase de control (throttling AIMD)
        if self.control_enabled:
            for nid in self._congested_signal_prev:
                for neighbor_id in self.agents_by_id[nid].neighbors:
                    self.agents_by_id[neighbor_id].congested_neighbors[nid] = 5  # cooldown

        for agent in self.agents_by_id.values():
            agent.control_phase()

        self._congested_signal_prev = congested_nodes_now

        # 6) registrar metricas del paso
        queue_lens = [len(a.queue) for a in self.agents_by_id.values()]
        n_edges = self.G.number_of_edges() * 2  # dirigidas
        prop_cong_edges = edges_over_capacity / max(1, edges_used_this_step)
        prop_cong_nodes = len(congested_nodes_now) / self.num_nodes
        mean_rate = sum(a.current_gen_rate for a in self.agents_by_id.values()) / self.num_nodes

        self.history["step"].append(self.steps)
        self.history["throughput"].append(delivered_this_step)
        self.history["mean_queue"].append(sum(queue_lens) / len(queue_lens))
        self.history["max_queue"].append(max(queue_lens))
        self.history["prop_congested_edges"].append(prop_cong_edges)
        self.history["prop_congested_nodes"].append(prop_cong_nodes)
        self.history["delivered_cum"].append(self.stats["delivered"])
        self.history["dropped_cum"].append(
            self.stats["dropped_queue_full"] + self.stats["dropped_ttl"]
        )
        self.history["generated_cum"].append(self.stats["generated"])
        self.history["mean_gen_rate"].append(mean_rate)

    def run(self, n_steps):
        for _ in range(n_steps):
            self.step()

    # -- tiempo de recuperacion (episodios de congestion -> vuelta a la normalidad) --
    def recovery_times(self, congestion_threshold=0.05):
        """
        Identifica episodios en los que la proporcion de nodos congestionados
        supera `congestion_threshold` y mide cuantos pasos tarda la red en
        volver a estar por debajo de ese umbral. Devuelve la lista de
        duraciones (en pasos) de cada episodio detectado.
        """
        prop = self.history["prop_congested_nodes"]
        times = []
        in_episode = False
        start = None
        for i, v in enumerate(prop):
            if not in_episode and v > congestion_threshold:
                in_episode = True
                start = i
            elif in_episode and v <= congestion_threshold:
                in_episode = False
                times.append(i - start)
        return times

    # -- resumen final de metricas obligatorias -------------------------------
    def summary(self):
        gen = self.stats["generated"]
        deliv = self.stats["delivered"]
        dropped = self.stats["dropped_queue_full"] + self.stats["dropped_ttl"]
        delivery_ratio = deliv / gen if gen else 0.0
        mean_latency = sum(self.latencies) / len(self.latencies) if self.latencies else float("nan")
        mean_queue_hist = sum(self.history["mean_queue"]) / len(self.history["mean_queue"])
        max_queue_hist = max(self.history["max_queue"])
        mean_prop_cong_edges = sum(self.history["prop_congested_edges"]) / len(
            self.history["prop_congested_edges"]
        )
        mean_prop_cong_nodes = sum(self.history["prop_congested_nodes"]) / len(
            self.history["prop_congested_nodes"]
        )
        total_throughput = deliv
        rec_times = self.recovery_times()
        mean_recovery = sum(rec_times) / len(rec_times) if rec_times else 0.0
        return {
            "generated": gen,
            "delivered": deliv,
            "dropped": dropped,
            "rejected_at_admission": self.stats["rejected_at_admission"],
            "delivery_ratio": delivery_ratio,
            "mean_latency": mean_latency,
            "mean_queue_len": mean_queue_hist,
            "max_queue_len": max_queue_hist,
            "prop_congested_edges": mean_prop_cong_edges,
            "prop_congested_nodes": mean_prop_cong_nodes,
            "total_delivered_throughput": total_throughput,
            "n_congestion_episodes": len(rec_times),
            "mean_recovery_time_steps": mean_recovery,
        }
