# Propuesta de Proyecto de Redes: STP vs MPLS

Nov 21, 2026 · @Emilio Puga

Versión 2, ajustada a la retroalimentación del profesor (propuesta aprobada). Prioriza los experimentos sobre la interfaz y sirve como documentación técnica del proyecto.

## Tema

Comparación experimental entre Spanning Tree Protocol (STP) y Multiprotocol Label Switching (MPLS) en el aprovechamiento de la capacidad de una topología redundante emulada en Mininet, presentada como una herramienta didáctica reproducible.

## Descripción

El proyecto mide, sobre una misma topología con dos caminos, cuánta capacidad aprovecha STP y cuánta aprovecha MPLS con dos LSPs estáticos. Un script reproducible ejecuta ambos escenarios, y un dashboard presenta los resultados leyendo archivos JSON.

**Problema.** STP evita bucles en capa 2 bloqueando enlaces redundantes, por lo que uno de los dos caminos queda ocioso. MPLS reenvía por etiquetas y permite asignar cada flujo a un camino distinto. La comparación también muestra el costo de MPLS: configuración manual y sin recuperación automática ante fallas.

**Topología base (fija):**

```
        ┌── S2 / R2 ──┐
H1 ══ S1 / R1           S4 / R4 ══ H2
        └── S3 / R3 ──┘

══  enlaces de acceso: 100 Mbps (mayor a 20 Mbps, para que no limiten)
──  enlaces de núcleo: 10 Mbps
```

En el escenario STP los nodos S1 a S4 son switches. En el escenario MPLS, R1 a R4 son routers Linux: R1 es el router de entrada que agrega la etiqueta, R2 y R3 la intercambian, y R4 es el router de salida que la quita.

**Originalidad.** A diferencia de configurar cada protocolo por separado, el proyecto compara ambos sobre la misma topología, con el mismo tráfico, y cuantifica la capacidad desperdiciada. El entregable es una herramienta didáctica y de comparación con resultados reales de emulación, que el curso puede reutilizar para enseñar.

## Decisiones técnicas

R1 reparte el tráfico según la dirección de destino: H2 tiene dos direcciones y cada una tiene su propia ruta etiquetada. El resto de decisiones mantiene iguales las condiciones de ambos escenarios.

| Decisión | Valor | Motivo |
| --- | --- | --- |
| Clasificación de flujos en R1 | H2 tiene dos direcciones (H2-a y H2-b). El tráfico hacia H2-a va por el LSP-A (vía R2) y el tráfico hacia H2-b por el LSP-B (vía R3) | Crear dos caminos no basta para repartir el tráfico; R1 necesita un criterio |
| Tráfico en el escenario STP | Los mismos dos flujos, hacia H2-a y H2-b | Comparación justa |
| Etiquetas (valores de ejemplo) | LSP-A: R1 agrega 100, R2 cambia 100 por 200, R4 la quita. LSP-B: R1 agrega 101, R3 cambia 101 por 201, R4 la quita | Se ajustan al configurar |
| Activar MPLS en el kernel | Cargar `mpls_router` y `mpls_iptunnel`. Poner `net.mpls.platform_labels` por encima de la etiqueta más alta y `net.mpls.conf.<interfaz>.input = 1` en cada interfaz que recibe paquetes etiquetados | Por defecto ambos valen 0 y el reenvío por etiquetas queda deshabilitado |
| STP | Open vSwitch con STP activado; si falla, bridges de Linux con STP | Plan B ya definido |
| Capacidades | Acceso a 100 Mbps y núcleo a 10 Mbps, iguales en ambos escenarios | Que el acceso no limite la comparación |
| Tráfico | Dos flujos `iperf3` simultáneos, con la misma duración (propuesta: 30 s) y salida en JSON (`-J`) | Mismas condiciones en ambos escenarios |
| Repeticiones | Al menos 5 por escenario | Reportar promedio y variación |
| Dashboard | Streamlit y Plotly, solo lee los JSON de resultados | La interfaz no es la prioridad |

Referencia: [documentación de sysctl de MPLS del kernel](https://docs.kernel.org/networking/mpls-sysctl.html).

## Experimentos y medición

El trabajo avanza en cuatro fases, y cada una se cierra con una verificación concreta antes de pasar a la siguiente.

1. **Fase 0, validación del entorno.** Instalar Mininet y activar MPLS en el kernel. Verificar, en este orden, la conectividad por un solo camino, la inserción y eliminación de etiquetas (vistas en Wireshark) y el funcionamiento de los dos LSPs.
2. **Fase 1, STP.** Mostrar brevemente la tormenta de broadcast sin STP, solo dentro del entorno emulado y separada de la red física. Con STP, identificar el enlace bloqueado y medir los dos flujos simultáneos.
3. **Fase 2, MPLS.** Configurar los dos LSPs y la clasificación por destino en R1. Capturar paquetes que confirmen el camino y la etiqueta de cada flujo.
4. **Fase 3, comparación.** Repetir cada escenario al menos cinco veces bajo las mismas condiciones. Reportar la tasa recibida por cada flujo, su suma, el promedio y la variación observada.

**Hipótesis:** con STP la suma de ambos flujos se acerca a 10 Mbps; con MPLS se acerca a 20 Mbps. Son valores de referencia, no resultados garantizados.

**Métricas:** tasa recibida por flujo y su suma (`iperf3`), latencia (`ping`) y capturas de Wireshark por flujo.

**Límite de las conclusiones:** los resultados valen para este montaje. La tasa de transferencia y la latencia permiten analizar rendimiento, pero no bastan para afirmar que un protocolo ofrece mejor calidad de servicio en general.

## Objetivos

**Objetivo general:** comparar experimentalmente el aprovechamiento de capacidad de una topología redundante emulada en Mininet bajo STP y bajo MPLS con dos LSPs estáticos, y presentar los resultados en una herramienta didáctica reproducible.

**Objetivos específicos:**

- Validar que Mininet y MPLS del kernel funcionan: conectividad, inserción y eliminación de etiquetas, y dos LSPs.
- Demostrar brevemente la tormenta de broadcast y su eliminación con STP dentro de la emulación.
- Medir con STP la tasa recibida por cada flujo y su suma.
- Configurar dos LSPs estáticos y asignar cada flujo a un LSP según su dirección de destino en H2.
- Medir con MPLS lo mismo, bajo condiciones idénticas y con al menos cinco repeticiones por escenario.
- Confirmar con capturas el camino y las etiquetas de cada flujo.
- Presentar el promedio y la variación de los resultados en un dashboard que lee JSON.
- Explicar los resultados limitando las conclusiones al montaje evaluado.

## Entregables

El entregable principal son los experimentos; el dashboard es un complemento.

- Configuraciones de STP y de MPLS: sysctl, rutas y etiquetas.
- Script reproducible en Python, con la API de Mininet, que monta la topología, ejecuta ambos escenarios y guarda los resultados en JSON.
- Mediciones: los JSON de todas las repeticiones de cada escenario.
- Capturas de Wireshark que muestran el camino y las etiquetas de cada flujo.
- Dashboard en Streamlit que lee esos JSON.
- Informe y presentación con la explicación de los resultados.

## Alcance

El proyecto usa solo la topología base, dos flujos de tráfico y emulación en Mininet.

| Dentro del alcance | Fuera del alcance |
| --- | --- |
| Topología base fija: 4 nodos de núcleo y 2 hosts | Topología editable y topologías grandes |
| STP sobre Open vSwitch (o bridges de Linux) | STP por VLAN (PVST, MSTP) |
| Dos LSPs estáticos con MPLS del kernel de Linux | Señalización con LDP o RSVP-TE |
| Dos flujos `iperf3` simultáneos y mediciones con `ping` | Afirmaciones generales sobre calidad de servicio |
| Capturas de paquetes con Wireshark | Redes físicas y VPNs sobre MPLS |
| Dashboard que lee archivos JSON | API, botón de ejecución y datos en vivo |

## Cronograma

El plan de ocho semanas del profesor se comprime a los días que quedan. Si presentamos el 8 de diciembre, los días extra van a las mediciones.

| Fechas | Etapa | Termina cuando |
| --- | --- | --- |
| Sáb 21 – lun 23 nov | Fase 0: validar el entorno | Ping por un camino, etiquetas vistas en Wireshark y los dos LSPs funcionando |
| Mar 24 – vie 27 nov | Fases 1 y 2: configurar STP y MPLS | Ambos escenarios corren con el mismo tráfico y hay capturas por flujo |
| Sáb 28 – lun 30 nov | Fase 3: medir y analizar | 5 repeticiones por escenario en JSON, con promedio y variación |
| Mar 1 dic | Tercer parcial | — |
| Mié 2 dic – presentación | Dashboard, informe y diapositivas | Los dos pueden explicar cada configuración y resultado |

Otras fechas: Deber 4 el jueves 26 de noviembre. La presentación es el 3 o el 8 de diciembre (por confirmar).

**Forma de trabajo:**

- Ambos participamos en cada fase. Quien no configura revisa y explica, para que los dos podamos defender cualquier parte.
- El código generado con asistentes de IA lo revisamos y aprobamos ambos, y lo entendemos línea por línea antes de integrarlo.
- Si MPLS no funciona hasta el martes 24 de noviembre, escribimos al profesor para acordar un ajuste del entorno o del alcance antes de continuar.

## Riesgos y consideraciones futuras

**Riesgos:**

- **Entorno.** Ninguno tiene aún Linux con Mininet. En la fase 0 se instala una máquina virtual Ubuntu; Docker también sirve, pero comparte el kernel del anfitrión y puede no traer los módulos MPLS.
- **MPLS deshabilitado por defecto.** Se revisan los sysctl desde el inicio; si faltan los módulos, se escala al profesor.
- **Open vSwitch falla.** Se usan bridges de Linux con STP.
- **Tiempo.** La fase 0 es la más incierta. Si se alarga, se recorta el dashboard antes que las mediciones.

**Consideraciones futuras:**

- **STP por VLAN (PVST, MSTP).** También reparte tráfico entre caminos, así que es la comparación más relevante contra MPLS.
- **Tiempo de recuperación ante fallas.** Medir STP, RSTP y un LSP de respaldo configurado a mano.
- **Herramienta extendida.** Topología editable, API con botón de ejecución y sistemas más complejos.
