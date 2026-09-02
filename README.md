# Modelo basado en agentes para control de congestión (Mesa / Python)

Simulación de una red de 50 nodos para el parcial de **Sistemas Complejos**.

## 1. Instalación

```bash
pip install -r requirements.txt
# equivalente a: pip install "mesa<3.0" networkx matplotlib
```


## 2. Ejecución rápida (demo / sustentación)

```bash
python3 demo.py --scenario alta --control --steps 300
python3 demo.py --scenario alta --steps 300          # sin control, para comparar
```

Imprime las métricas obligatorias en consola y guarda una imagen del
estado de la red en `outputs/`.

## 3. Experimento completo (los 3 escenarios × con/sin control × 10 repeticiones)

```bash
python3 experiments.py
```

Genera en `outputs/`:
- `runs_summary.csv` — una fila por corrida individual (60 filas: 3 escenarios × 2 condiciones × 10 repeticiones).
- `runs_aggregate.csv` — promedio y desviación estándar por (escenario, condición).
- `history_<escenario>_control_<True|False>.csv` — serie de tiempo paso a paso de la primera repetición de cada combinación.

## 4. Gráficas

```bash
python3 visualize.py
```

Genera en `outputs/`:
- `network_snapshot_*.png` — mapa de la red coloreado por estado de congestión (verde = normal, amarillo = próximo a congestión, rojo = congestionado), con los nodos *hotspot* resaltados en azul.
- `timeseries_<escenario>.png` — evolución temporal de cola media, proporción de nodos congestionados y throughput, comparando sin/con control.
- `comparison_bars.png` — barras comparativas (media ± desviación estándar) de tasa de entrega, latencia, proporción de nodos congestionados y paquetes descartados, para los 3 escenarios.

## 5. Estructura de agentes, estados y reglas (Actividad 1)

- **Agente (α):** `NetworkNodeAgent`, un nodo de comunicación con:
  - **Estado:** cola FIFO finita (`queue`), tasa de generación actual (`current_gen_rate`), nivel de congestión propio (`status` ∈ {normal, warning, critical}), y memoria de vecinos que han señalado congestión (`congested_neighbors`).
  - **Percepción:** ocupación de su propia cola (`occupancy`) + señales de congestión recibidas de vecinos (información de control, ver Net Interaction abajo).
  - **Acciones:** generar paquete propio, reenviar paquete (elegir siguiente salto), retener paquete (backpressure implícito cuando el salto preferido está marcado congestionado y no hay alternativa), y regular su propia tasa de generación (throttling).

- **¿Por qué la congestión es emergente?** Ningún agente decide "voy a congestionar la red". Cada nodo solo genera tráfico y reenvía según una tabla local de enrutamiento; la saturación de un enlace o cola surge de la **suma no coordinada** de miles de decisiones locales de miles de pasos, concentradas además por el patrón de tráfico hacia unos pocos nodos *hotspot*. El patrón global (zonas congestionadas, oscilaciones, recuperación) no está programado en ningún agente individual: emerge de la interacción repetida α ↔ β.

## 6. Diseño de la red (Actividad 2)

| Elemento | Valor / regla | Justificación |
|---|---|---|
| Topología | `networkx.newman_watts_strogatz_graph(50, k=4, p=0.12)` — anillo con enlaces adicionales | Conexa por construcción (contiene el anillo base); genera heterogeneidad de grado realista sin depender de un modelo puramente aleatorio |
| Capacidad de enlace | 1 paquete/paso por dirección | Valor deliberadamente bajo para poder observar congestión real en pocos cientos de pasos sin necesitar decenas de miles de nodos/pasos |
| Tamaño de cola | 10 paquetes por nodo | Cola pequeña y finita: fuerza decisiones de control antes de que sea trivial absorber toda la carga |
| Generación de tráfico | Bernoulli por paso y por nodo, con tasa `base_gen_rate` variable por escenario | Permite escalar la carga ofrecida linealmente para crear los 3 escenarios |
| Patrón de destinos | 55% del tráfico dirigido a 3 nodos *hotspot* (gateways), 45% uniforme | Crea puntos de convergencia de flujo realistas (ej. salidas a internet / servidores), en vez de diluir la carga uniformemente |
| Enrutamiento | Tabla de siguiente-salto por camino más corto (`next_hop_table`), precomputada una vez por nodo | Cada agente solo conoce su propia fila (regla local); equivale a un protocolo de estado de enlace ya convergido |

## 7. Detección de congestión (Actividad 3)

Indicador cuantitativo: **ocupación de la cola** = `len(queue) / max_queue_size`.

| Estado | Condición | Color en las figuras |
|---|---|---|
| Normal | ocupación < 0.5 | verde |
| Próximo a congestión | 0.5 ≤ ocupación < 0.8 | amarillo |
| Congestionado | ocupación ≥ 0.8 | rojo |

También se mide congestión de **enlace** como la proporción de aristas donde la demanda de tráfico superó la capacidad disponible en ese paso (`prop_congested_edges`).

## 8. Control distribuido (Actividad 4)

No se descartan paquetes por congestión sin más: el único descarte por
congestión es el *tail-drop* cuando la cola destino está genuinamente
llena (límite físico de buffer, estándar en redes). El **mecanismo de
control** combina tres acciones locales, cada una activable/desactivable
con `control_enabled`:

1. **Regulación de tasa (AIMD)** — cada nodo aumenta aditivamente su
   tasa de generación cuando está en estado normal, y la reduce
   multiplicativamente (×0.5) cuando está en `warning`/`critical`
   (análogo a TCP). Reduce el tráfico inyectado por la fuente antes de
   que llegue a saturar la red.
2. **Señal de congestión a vecinos** — cuando un nodo entra en estado
   `critical`, en el siguiente paso sus vecinos directos lo marcan como
   "evitar" durante 5 pasos (`congested_neighbors`), similar a una
   notificación explícita de congestión (ECN).
3. **Desvío acotado (rerouting)** — un nodo que necesita reenviar un
   paquete y detecta que su salto primario está marcado como congestionado
   busca un vecino alternativo cuya distancia al destino no aumente en
   más de `detour_slack` (2) saltos. Si no existe alternativa razonable,
   el paquete simplemente espera en la cola (**backpressure**: la
   congestión se propaga hacia atrás en vez de perderse).

## 9. Escenarios y repeticiones (Actividad 5)

| Escenario | `base_gen_rate` | Comportamiento esperado (sin control) |
|---|---|---|
| Carga baja | 0.08 | ~99% de entrega, congestión prácticamente nula |
| Carga media | 0.25 | Congestión temporal en ~5% de los nodos, entrega ~86% |
| Carga alta | 0.50 | Congestión persistente (~22% de nodos), entrega ~58% |

`experiments.py` corre **10 repeticiones** por combinación (escenario ×
control), usando semillas `1000..1009` — la **misma semilla** se usa en
la condición sin control y con control, de modo que la topología y la
secuencia de generación de tráfico de fondo son comparables y la única
diferencia es el mecanismo de control. 300 pasos por corrida son
suficientes para que las métricas se estabicen tras el transitorio
inicial (~30-50 pasos).

## 10. Resultados observados (referencia, generados con las semillas de arriba)

| Escenario | Control | Entrega | Latencia media | % nodos congestionados | Descartados |
|---|---|---|---|---|---|
| Baja | No | 0.989 | 2.75 | 0.000 | 0 |
| Baja | Sí | 0.991 | 2.71 | 0.000 | 0 |
| Media | No | 0.863 | 5.49 | 0.051 | 438 |
| Media | Sí | 0.932 | 6.69 | 0.023 | 124 |
| Alta | No | 0.584 | 8.35 | 0.216 | 2638 |
| Alta | Sí | 0.833 | 11.42 | 0.077 | 434 |

**Lectura para el análisis:** el control mejora sustancialmente la tasa
de entrega y reduce drásticamente pérdidas y proporción de nodos
congestionados, a costa de **mayor latencia media** (los paquetes
esperan/se desvían en vez de perderse) — es el trade-off clásico de
todo mecanismo de control de congestión y da pie a discutir las
preguntas orientadoras 4 y 5 del enunciado.

## 11. Formalización Net Interaction (referencia rápida para el documento)

| Elemento | Notación | En este modelo |
|---|---|---|
| Agentes | α, β | Instancias de `NetworkNodeAgent` (0..49) |
| Interacción | α ↔ β | Arista de `self.G`, dirigida en cada paso por `desired[(u,v)]` |
| Información | m | `Packet` (dato) o señal implícita de pertenencia a `congested_neighbors` (control) |
| Red | N | `self.G` (grafo `networkx`) |
| Regla local | (α↔β, m) → estado′ | `get_next_hop`, `control_phase`, actualización de `queue`/`status` en `NetworkCongestionModel.step` |

