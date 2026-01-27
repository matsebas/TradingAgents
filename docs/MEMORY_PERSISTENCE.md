# Memory Persistence - Documentación

## 📋 Resumen de Cambios

Se implementó **persistencia de datos** en la clase `FinancialSituationMemory` para que las situaciones financieras y recomendaciones se almacenen permanentemente en disco usando ChromaDB.

## ✨ Características

### Antes (En Memoria)
- ❌ Datos se perdían al reiniciar la aplicación
- ❌ No había acumulación de conocimiento histórico
- ❌ Embeddings se generaban cada vez
- ❌ Configuración con `allow_reset=True`

### Después (Persistente)
- ✅ Datos se guardan en disco permanentemente
- ✅ Acumulación de conocimiento entre sesiones
- ✅ Embeddings se reutilizan (ahorro de API calls)
- ✅ Usar `get_or_create_collection` para reutilizar datos existentes

## 🔧 Implementación

### Cambios en el Código

```python
# ANTES
self.chroma_client = chromadb.Client(Settings(allow_reset=True))
self.situation_collection = self.chroma_client.create_collection(name=name)

# DESPUÉS
persist_path = config.get("memory_path", "./chroma_db")
self.chroma_client = chromadb.PersistentClient(path=persist_path)
self.situation_collection = self.chroma_client.get_or_create_collection(name=name)
```

### Configuración

En tu archivo de configuración (`DEFAULT_CONFIG` o config personalizada):

```python
config = {
    "llm_provider": "google",
    "gemini_api_key": os.getenv("GEMINI_API_KEY"),
    "memory_path": "./chroma_db",  # Directorio para almacenar la base de datos
    # ... otras configuraciones
}
```

Si no especificas `memory_path`, se usará `./chroma_db` por defecto.

## 📁 Estructura de Archivos

```
TradingAgents/
├── chroma_db/                    # Base de datos persistente de ChromaDB
│   ├── chroma.sqlite3           # Índice SQLite
│   └── [uuid]/                  # Datos de vectores por colección
├── tradingagents/
│   └── agents/
│       └── utils/
│           └── memory.py        # ✏️ Modificado para persistencia
└── tests/
    └── test_memory_persistence.py  # ✅ Nuevo test
```

## 🧪 Testing

Se creó un test completo que verifica:

### Test 1: Persistencia Básica
1. ✅ Crear memoria y agregar situaciones
2. ✅ Cerrar instancia
3. ✅ Crear nueva instancia y verificar datos persisten
4. ✅ Verificar integridad de datos (count, queries, similarity scores)
5. ✅ Agregar más datos y verificar acumulación
6. ✅ Verificación final

### Test 2: Múltiples Colecciones
1. ✅ Crear dos colecciones independientes
2. ✅ Agregar datos diferentes a cada una
3. ✅ Verificar que persisten independientemente

### Ejecutar Tests

```bash
# Ejecutar test de persistencia
python tests/test_memory_persistence.py

# Salida esperada:
# ✨ ALL TESTS PASSED! Memory persistence is working correctly.
# 🎉 All tests passed successfully!
```

## 🎯 Casos de Uso

### Ejemplo 1: Memoria de Situaciones de Trading

```python
from tradingagents.agents.utils.memory import FinancialSituationMemory

config = {
    "llm_provider": "google",
    "gemini_api_key": os.getenv("GEMINI_API_KEY"),
    "memory_path": "./trading_memory"
}

# Primera sesión
memory = FinancialSituationMemory(name="trading_situations", config=config)
memory.add_situations([
    ("Alta volatilidad en tech", "Reducir exposición a growth stocks"),
    ("Inflación subiendo", "Considerar bonos indexados")
])

# Segunda sesión (después de reiniciar)
memory = FinancialSituationMemory(name="trading_situations", config=config)
# ✅ Los datos anteriores siguen disponibles
results = memory.get_memories("Mercado tech volátil", n_matches=2)
```

### Ejemplo 2: Múltiples Agentes con Memorias Separadas

```python
# Agente de Stocks
stock_memory = FinancialSituationMemory(
    name="stock_agent_memory", 
    config={**config, "memory_path": "./memories/stocks"}
)

# Agente de Crypto
crypto_memory = FinancialSituationMemory(
    name="crypto_agent_memory",
    config={**config, "memory_path": "./memories/crypto"}
)

# Cada uno mantiene su memoria independiente y persistente
```

## 💡 Beneficios

1. **Eficiencia**
   - No regenerar embeddings en cada ejecución
   - Reducción de API calls a Gemini/OpenAI
   - Inicio más rápido de la aplicación

2. **Continuidad**
   - Agentes mantienen contexto histórico
   - Aprendizaje acumulativo
   - Mejores decisiones basadas en experiencia

3. **Confiabilidad**
   - Backup automático de conocimiento
   - Recuperación ante fallos
   - Análisis histórico de recomendaciones

4. **Escalabilidad**
   - Múltiples colecciones independientes
   - Separación por agente/estrategia/mercado
   - Fácil mantenimiento

## 🔍 Verificación

### Ver contenido de la base de datos

```python
from tradingagents.agents.utils.memory import FinancialSituationMemory

memory = FinancialSituationMemory(name="mi_memoria", config=config)

# Ver cantidad de situaciones almacenadas
print(f"Situaciones: {memory.situation_collection.count()}")

# Ver todas las situaciones
results = memory.situation_collection.get()
for i, doc in enumerate(results['documents']):
    print(f"{i+1}. {doc}")
    print(f"   → {results['metadatas'][i]['recommendation']}\n")
```

## 🚨 Consideraciones

### Backup
- Haz backup periódico del directorio `chroma_db`
- Considera usar git-lfs para archivos grandes si vas a versionar

### Limpieza
```python
# Limpiar toda la colección (cuidado!)
memory.situation_collection.delete()

# O eliminar la base de datos completa
import shutil
shutil.rmtree("./chroma_db")
```

### Migración
- Si cambias de modelo de embeddings, necesitarás regenerar todos los vectores
- Considera versionar tus colecciones por modelo: `trading_situations_gemini`

## 📊 Métricas de Ejemplo

Después de ejecutar los tests:
```
📊 Summary:
   - Initial situations: 3
   - Added situations: 1
   - Final total: 4
   - Data persisted across 3 instances
   - Storage location: /var/folders/.../tmp...
```

## 🔗 Referencias

- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Gemini Embeddings API](https://ai.google.dev/gemini-api/docs/embeddings)
- [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings)

---

**Última actualización:** Enero 2026  
**Autor:** TradingAgents Project
