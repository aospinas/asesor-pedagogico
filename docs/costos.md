# Costos

| Concepto | Plan | Costo | Límite que hay que vigilar |
| --- | --- | --- | --- |
| Render | Gratis | $0 | 512 MB de RAM; se duerme a los 15 min sin visitas |
| Supabase | Gratis | $0 | 500 MB de base de datos, 1 GB de archivos; pausa tras 1 semana sin uso |
| GitHub + Actions | Gratis (repo público) | $0 | — |
| Ollama | Local | $0 | Velocidad del PC |
| OpenRouter (modelos gratis) | Gratis | $0 | Límite de peticiones por minuto |
| API de OpenAI | Pago por uso | Variable | Ver tabla de abajo |

## Modelo de OpenAI elegido

Completar el día que se configure (no inventar precios: copiarlos de la página de precios de OpenAI).

| Modelo | Precio entrada (USD por millón de tokens) | Precio salida (USD por millón de tokens) | Fecha consultada |
| --- | --- | --- | --- |
| `gpt-6-luna` (D-19) | 0,10 | 0,50 | 17-nov-2026 (developers.openai.com) |

En Render: `LLM_MODEL=gpt-6-luna`, `LLM_PRECIO_ENTRADA_USD=0.1`, `LLM_PRECIO_SALIDA_USD=0.5`, `LLM_ESFUERZO=low`. Si la calidad no alcanza, `gpt-6.1-terra` (1,00 / 5,00) sin tocar código: el administrador pone en la configuración de IA el modelo **y sus dos precios**. Si deja los precios vacíos, el panel usa los de `LLM_PRECIO_*` y mostraría un costo equivocado. Cada criterio gasta unos 15.000 a 17.000 tokens con el material completo (hasta 60.000 caracteres, que se mandan una vez por criterio) y menos si la entrega es corta: una evaluación de 3 a 6 criterios queda entre 20.000 y 100.000 tokens. El tope es 300.000 por evaluación. Con $3 de crédito, `gpt-6-luna` alcanza para cientos de evaluaciones (a unos $0,01 cada una). Confirmarlo en "Consumo real" con las primeras evaluaciones.

## Consumo real

Lo llena el panel de costos (RF-20). Copiar aquí el total al final del proyecto para la sustentación.

| Laboratorios evaluados | Tokens de entrada | Tokens de salida | Costo total USD |
| --- | --- | --- | --- |
| | | | |
