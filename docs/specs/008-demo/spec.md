# Spec 008 — Demo: datos, frontend y modo simulación

**Rama:** `spec/008-demo` · **Estado:** terminada · **Depende de:** 007

## Contexto

El entregable 3 del enunciado es una demo funcional y recomienda un frontend sencillo que ilustre el flujo completo desde la interfaz hasta DynamoDB y Redis. En la sustentación hay que mostrar, no solo contar.

## Objetivo

Que con un comando el sistema quede desplegado y con datos, y que una página permita recorrer los tres roles viendo de dónde sale cada respuesta.

## Alcance

Incluye: script de datos iniciales, script para ver la tabla, script de despliegue, frontend estático servido por un cuarto contenedor y un servidor de simulación sin Docker.

No incluye: nada que cambie el API.

## Requisitos

- **R1.** `scripts/seed.py` carga cuentas, cursos, ofertas, matrículas y notas llamando al API, y verifica el código HTTP de cada llamada: es también la prueba de punta a punta.
- **R2.** El seed es idempotente: se puede ejecutar dos veces.
- **R3.** El seed escribe `frontend/config.js` con la URL del API para el navegador.
- **R4.** El frontend funciona sin internet: sin CDN ni fuentes externas.
- **R5.** El frontend muestra cada petición con método, ruta, código, duración y `_fuente`.
- **R6.** Cada vista dice qué operación de DynamoDB o Redis hay detrás.
- **R7.** `scripts/ver_tabla.py` muestra los ítems agrupados por partición, desde la tabla o desde un índice.
- **R8.** `scripts/servidor_local.py` levanta API y frontend en un proceso, con moto y fakeredis, usando los mismos handlers.

## Criterios de aceptación

- [x] El seed completa todas sus llamadas con el código esperado contra el servidor de simulación.
- [x] Recorrido en navegador de los tres roles sin errores de JavaScript: login, catálogo, matricular (con y sin cupo), horario, cambio de grupo, lista de clase, aprobar, calificar, pendientes y ranking.
- [x] La segunda lectura del catálogo aparece como `CACHÉ` en la traza.
- [ ] El mismo recorrido contra LocalStack: **pendiente de ejecutar en un equipo con Docker**.
