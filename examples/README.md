# Examples - Memory Persistence

## 🎯 Descripción

Esta carpeta contiene scripts de ejemplo que demuestran el uso de la persistencia de memoria en TradingAgents.

## 📚 Ejemplos Disponibles

### `demo_memory_persistence.py`

Demo interactivo que muestra cómo:
- ChromaDB persiste datos entre ejecuciones
- Se acumula conocimiento histórico
- Funciona la búsqueda por similitud semántica

**Uso:**
```bash
# Primera ejecución - crea y guarda datos
python examples/demo_memory_persistence.py

# Segunda ejecución - recupera datos persistidos
python examples/demo_memory_persistence.py
```

**Salida esperada:**

Primera ejecución:
```
🆕 First run detected - Adding initial situations...
   ✅ Added 4 situations to memory
   💡 Run this script again to see the data persist!
```

Segunda ejecución:
```
✨ Data persisted from previous run!

📚 Stored situations (4):
1. Situation: High inflation rate with rising interest rates...
   → Recommendation: Consider defensive sectors...
...
```

## 🧪 Tests

Para ejecutar los tests de persistencia:

```bash
python tests/test_memory_persistence.py
```

## 📖 Documentación Completa

Para más detalles sobre la implementación de persistencia, consulta:
- [`docs/MEMORY_PERSISTENCE.md`](../docs/MEMORY_PERSISTENCE.md)

## 🔧 Configuración

Los ejemplos usan la configuración por defecto del proyecto:
- **Provider:** Google Gemini
- **Embedding Model:** gemini-embedding-001
- **Storage:** ChromaDB persistente

Asegúrate de tener configurada la variable de entorno:
```bash
export GEMINI_API_KEY="tu-api-key"
```

## 🧹 Limpieza

Para limpiar la base de datos de demo:
```bash
rm -rf demo_chroma_db
```
