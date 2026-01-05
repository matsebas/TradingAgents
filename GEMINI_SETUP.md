# 🚀 Guía Completa: Configuración de Gemini para TradingAgents

**Última actualización:** Enero 2026  
**Biblioteca:** `google.genai` (actualizada)

---

## 📋 Índice

1. [Resumen de Cambios](#resumen-de-cambios)
2. [Configuración Rápida](#configuración-rápida)
3. [¿Qué usa Gemini?](#qué-usa-gemini)
4. [Detalles Técnicos](#detalles-técnicos)
5. [Verificación](#verificación)
6. [Troubleshooting](#troubleshooting)

---

## ✅ Resumen de Cambios

### Configuración Actual del Proyecto

#### 1. **LLM Principal: Gemini** (en lugar de OpenAI)
```python
# tradingagents/default_config.py
"llm_provider": "google"
"deep_think_llm": "gemini-3-flash-preview"
"quick_think_llm": "gemini-3-flash-preview"
```

#### 2. **Data Vendors: Gemini** (en lugar de Alpha Vantage)
```python
"data_vendors": {
    "core_stock_apis": "yfinance",      # Precios - NO requiere API key
    "technical_indicators": "yfinance",  # Indicadores - NO requiere API key
    "fundamental_data": "gemini",        # ✅ Requiere GEMINI_API_KEY
    "news_data": "gemini",               # ✅ Requiere GEMINI_API_KEY
}
```

#### 3. **Biblioteca Actualizada: google.genai**
- ❌ **Antes:** `google.generativeai` (deprecada)
- ✅ **Ahora:** `google.genai` (oficial y con soporte activo)

---

## 🔑 Configuración Rápida

### Paso 1: Obtener API Key

1. Ve a **[Google AI Studio](https://aistudio.google.com/)**
2. Inicia sesión con tu cuenta de Google
3. Haz clic en **"Get API Key"** en el panel izquierdo
4. Crea una nueva API key o copia una existente
5. Copia tu API key (formato: `AIzaSy...`)

### Paso 2: Configurar Variables de Entorno

**Importante:** Solo necesitas **UNA API KEY** de Gemini, pero debes configurarla en **DOS** variables:

```bash
export GEMINI_API_KEY="AIzaSy...tu-api-key-real"
export GOOGLE_API_KEY="AIzaSy...tu-api-key-real"  # La misma key
```

**¿Por qué dos variables?**
- `GEMINI_API_KEY` → Para el vendor de datos (noticias y fundamentales con `google.genai`)
- `GOOGLE_API_KEY` → Para los LLMs de langchain (`ChatGoogleGenerativeAI`)

#### Opción A: Temporal (solo para sesión actual)
```bash
export GEMINI_API_KEY="AIzaSy...tu-api-key-real"
export GOOGLE_API_KEY="AIzaSy...tu-api-key-real"
```

#### Opción B: Permanente (recomendado)
```bash
echo 'export GEMINI_API_KEY="AIzaSy...tu-api-key-real"' >> ~/.zshrc
echo 'export GOOGLE_API_KEY="AIzaSy...tu-api-key-real"' >> ~/.zshrc
source ~/.zshrc
```

#### Opción C: Archivo .env
Crea o edita `.env` en la raíz del proyecto:
```bash
GEMINI_API_KEY=AIzaSy...tu-api-key-real
GOOGLE_API_KEY=AIzaSy...tu-api-key-real
```

### Paso 3: Verificar Configuración

Ejecuta el script de verificación:
```bash
cd /Users/msebastiao/Downloads/git/labs/TradingAgents
python verify_gemini.py
```

**Resultado esperado:**
```
✅ PASS: Variables de entorno
✅ PASS: Configuración del proyecto
✅ PASS: Conexión con Gemini (google.genai)
✅ PASS: ChatGoogleGenerativeAI (langchain)

🎉 Todo configurado correctamente! Gemini está listo para usar.
```

---

## 🤖 ¿Qué usa Gemini?

### 1. LLMs de Trading (Todos los Agentes)

Todos estos agentes usan **Gemini** a través de `ChatGoogleGenerativeAI`:

- ✅ **Bull Researcher** - Análisis optimista
- ✅ **Bear Researcher** - Análisis pesimista  
- ✅ **Market Analyst** - Análisis técnico
- ✅ **News Analyst** - Análisis de noticias
- ✅ **Fundamentals Analyst** - Análisis fundamental
- ✅ **Social Media Analyst** - Análisis de redes sociales
- ✅ **Risk Manager** - Gestión de riesgo
- ✅ **Trader** - Decisiones de trading

**Modelo:** `gemini-3-flash-preview`

### 2. Data Vendors (Fuentes de Datos)

**Con Gemini (requiere API key):**
- ✅ **Noticias de empresas** - Social Media, Reddit, etc.
- ✅ **Noticias globales** - Macroeconómicas y de mercado
- ✅ **Datos fundamentales** - PE, PS, Cash Flow, etc.

**Sin Gemini (gratis, no requiere API key):**
- ✅ **Precios OHLCV** - yfinance
- ✅ **Indicadores técnicos** - yfinance (RSI, MACD, etc.)
- ✅ **Balance sheets** - yfinance
- ✅ **Cash flow statements** - yfinance
- ✅ **Income statements** - yfinance

### 3. Características Especiales

- ✅ **Google Search Grounding** - Búsqueda en tiempo real integrada
- ✅ **Fallback Automático** - Si Gemini falla, usa otros vendors
- ✅ **Multi-vendor Support** - Compatible con OpenAI, Alpha Vantage, etc.

---

## 🔧 Detalles Técnicos

### Archivos Modificados

#### 1. `tradingagents/default_config.py`
```python
DEFAULT_CONFIG = {
    # LLM settings
    "llm_provider": "google",                    # Cambió de "openai"
    "deep_think_llm": "gemini-3-flash-preview",  # Cambió de "o4-mini"
    "quick_think_llm": "gemini-3-flash-preview", # Cambió de "gpt-4o-mini"
    
    # Gemini settings
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "gemini_model": "gemini-3-flash-preview",
    
    # Data vendors
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "gemini",    # Cambió de "alpha_vantage"
        "news_data": "gemini",           # Cambió de "alpha_vantage"
    },
}
```

#### 2. `tradingagents/dataflows/gemini.py`
Vendor de Gemini con 3 funciones principales:

```python
from google import genai
from google.genai import types

# 1. Noticias de empresas
def get_stock_news_gemini(query, start_date, end_date):
    client = genai.Client(api_key=config.get("gemini_api_key"))
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
        config=types.GenerateContentConfig(...),
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    return response.text

# 2. Noticias globales
def get_global_news_gemini(curr_date, look_back_days=7, limit=5):
    # Similar a get_stock_news_gemini
    ...

# 3. Datos fundamentales
def get_fundamentals_gemini(ticker, curr_date):
    # Similar a get_stock_news_gemini
    ...
```

#### 3. `tradingagents/dataflows/interface.py`
Integración del vendor en el sistema de routing:

```python
def route_to_vendor(tool_name, **kwargs):
    # Sistema automático que detecta qué vendor usar
    # Prioridad: tool_vendors > data_vendors > default
    vendor = determine_vendor(tool_name)
    
    if vendor == "gemini":
        return call_gemini_vendor(tool_name, **kwargs)
    elif vendor == "yfinance":
        return call_yfinance_vendor(tool_name, **kwargs)
    # ... otros vendors
```

#### 4. `tradingagents/graph/trading_graph.py`
Inicialización de LLMs:

```python
if self.config["llm_provider"].lower() == "google":
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    self.deep_thinking_llm = ChatGoogleGenerativeAI(
        model=self.config["deep_think_llm"]
    )
    self.quick_thinking_llm = ChatGoogleGenerativeAI(
        model=self.config["quick_think_llm"]
    )
```

### Migración de google.generativeai a google.genai

**Cambios en la API:**

```python
# ❌ ANTES (google.generativeai - DEPRECADO)
import google.generativeai as genai

genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview",
    tools='google_search_retrieval'
)
response = model.generate_content(
    prompt,
    generation_config=genai.GenerationConfig(...)
)

# ✅ AHORA (google.genai - OFICIAL)
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)
response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=prompt,
    config=types.GenerateContentConfig(...),
    tools=[types.Tool(google_search=types.GoogleSearch())]
)
```

**Beneficios:**
- ✅ Soporte activo y actualizaciones
- ✅ Sin warnings de deprecación
- ✅ API más moderna y consistente
- ✅ Preparado para nuevas características

---

## 🧪 Verificación

### Scripts de Verificación Disponibles

#### 1. `verify_gemini.py` - Verificación completa
```bash
python verify_gemini.py
```

**Verifica:**
- ✅ Variables de entorno (`GEMINI_API_KEY`)
- ✅ Configuración del proyecto (`default_config.py`)
- ✅ Conexión con Gemini (vendor con `google.genai`)
- ✅ ChatGoogleGenerativeAI (langchain)

#### 2. `test_gemini_functions.py` - Test de funciones
```bash
python test_gemini_functions.py
```

**Verifica:**
- ✅ Imports de funciones de gemini.py
- ✅ Configuración correcta
- ✅ Creación de cliente de Gemini

### Ejecución Normal del Proyecto

```bash
# Opción 1: Script principal
python main.py

# Opción 2: CLI interactivo
python cli/main.py
```

**Logs esperados:**
```
DEBUG: get_fundamentals - Primary: [gemini]
DEBUG: get_news - Primary: [gemini]
INFO: Using Google Gemini LLM (gemini-3-flash-preview)
```

---

## 💡 Ventajas de Usar Gemini

### 1. **Gratis y Generoso**
- ✅ **15 requests/minuto**
- ✅ **1,500 requests/día**
- ✅ **1 millón tokens/minuto**
- ✅ Sin tarjeta de crédito requerida

### 2. **Google Search Integrado**
- ✅ Búsqueda en tiempo real
- ✅ Datos más actualizados
- ✅ Mejor para noticias y fundamentales
- ✅ Sin necesidad de APIs adicionales

### 3. **Un Solo Proveedor**
- ✅ No necesitas OpenAI API key
- ✅ No necesitas Alpha Vantage API key
- ✅ Más simple y económico
- ✅ Una sola configuración

### 4. **Fallback Automático**
- ✅ Si Gemini falla, usa otros vendors
- ✅ Sistema robusto y confiable
- ✅ Nunca te quedas sin datos

### 5. **Modelos Potentes**
- ✅ `gemini-3-flash-preview` - Rápido y eficiente
- ✅ `gemini-2.5-flash` - Versión estable
- ✅ `gemini-2.5-pro` - Para análisis profundo
- ✅ Multimodal (texto, imágenes, video)

---

## ❓ Troubleshooting

### Error: "API key not valid"
**Causa:** API key incorrecta o inválida

**Solución:**
1. Verifica tu API key en [Google AI Studio](https://aistudio.google.com/)
2. Asegúrate de que está activa
3. Copia y pega correctamente (sin espacios)
4. Vuelve a configurar las variables de entorno

```bash
echo $GEMINI_API_KEY  # Debe mostrar tu API key
echo $GOOGLE_API_KEY  # Debe mostrar tu API key
```

### Error: "Module not found: google.genai"
**Causa:** Dependencias no instaladas

**Solución:**
```bash
pip install google-genai
# o
pip install -r requirements.txt
```

### Error: "GEMINI_API_KEY not set" o "GOOGLE_API_KEY not set"
**Causa:** Variables de entorno no configuradas

**Solución:**
```bash
# Configurar temporalmente
export GEMINI_API_KEY="tu-api-key"
export GOOGLE_API_KEY="tu-api-key"

# Configurar permanentemente
echo 'export GEMINI_API_KEY="tu-api-key"' >> ~/.zshrc
echo 'export GOOGLE_API_KEY="tu-api-key"' >> ~/.zshrc
source ~/.zshrc
```

### Los agentes no usan Gemini
**Causa:** Configuración incorrecta en `default_config.py`

**Solución:**
1. Verifica `tradingagents/default_config.py`
2. Debe tener: `"llm_provider": "google"`
3. Si no, edita el archivo y cambia el valor

### Data vendors no usan Gemini
**Causa:** Configuración de vendors incorrecta

**Solución:**
1. Verifica `tradingagents/default_config.py`
2. En `data_vendors`, debe tener:
   ```python
   "fundamental_data": "gemini",
   "news_data": "gemini",
   ```

### Warning: "google.generativeai is deprecated"
**Causa:** Código antiguo usando biblioteca deprecada

**Solución:**
- ✅ Ya migrado a `google.genai`
- ✅ Ejecuta `python verify_gemini.py` para confirmar
- ✅ No deberías ver este warning

### Error: "Rate limit exceeded"
**Causa:** Demasiadas requests en poco tiempo

**Solución:**
1. Espera 1 minuto antes de volver a intentar
2. Límites de Gemini:
   - 15 requests/minuto
   - 1,500 requests/día
3. Considera usar caché o reducir frecuencia de requests

### Error al conectar con Google Search
**Causa:** Google Search grounding puede fallar ocasionalmente

**Solución:**
- ✅ El sistema tiene fallback automático
- ✅ Intentará con otros vendors
- ✅ Revisa logs para ver qué vendor se usó

---

## 🎯 Checklist de Configuración

- [ ] API Key obtenida de Google AI Studio
- [ ] `GEMINI_API_KEY` configurada
- [ ] `GOOGLE_API_KEY` configurada (misma key)
- [ ] `verify_gemini.py` ejecutado exitosamente
- [ ] Todos los tests pasan (✅ × 4)
- [ ] Proyecto ejecuta sin errores
- [ ] Logs muestran "Primary: [gemini]"

---

## 📚 Archivos de Referencia

### Scripts de Verificación
- `verify_gemini.py` - Verificación completa del sistema
- `test_gemini_functions.py` - Test de funciones específicas

### Archivos de Configuración
- `tradingagents/default_config.py` - Configuración principal
- `tradingagents/dataflows/config.py` - Gestión de configuración

### Implementación
- `tradingagents/dataflows/gemini.py` - Vendor de Gemini
- `tradingagents/dataflows/interface.py` - Sistema de routing
- `tradingagents/graph/trading_graph.py` - Inicialización de LLMs

---

## 📝 Resumen Final

### ✅ Lo que necesitas:
1. **Una API key de Gemini** (gratis)
2. **Dos variables de entorno** (`GEMINI_API_KEY` y `GOOGLE_API_KEY` con la misma key)
3. **Ejecutar** `python verify_gemini.py`

### ✅ Lo que obtienes:
- **Todos los agentes** usando Gemini
- **Noticias y fundamentales** con Google Search
- **Precios e indicadores** gratis con yfinance
- **Sin necesidad de OpenAI o Alpha Vantage**

### ✅ Bibliotecas actualizadas:
- `google.genai` (oficial, con soporte activo)
- `langchain-google-genai` (para ChatGoogleGenerativeAI)

---

## 🚀 ¡Listo para usar!

El proyecto está 100% configurado para usar Gemini. Solo necesitas:

```bash
# 1. Configurar API key
export GEMINI_API_KEY="tu-api-key"
export GOOGLE_API_KEY="tu-api-key"

# 2. Verificar
python verify_gemini.py

# 3. Ejecutar
python main.py
```

**¡Disfruta de tus agentes de trading con Gemini!** 🎉

---

**Documentación generada para TradingAgents**  
**Versión: Enero 2026**  
**Biblioteca: google.genai (actualizada)**

