from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging
import requests
import base64
import json
import os
import tempfile
import uuid
import io
import time
import re

# Configurar logs primero
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carpeta donde vive este script (backend/). Usamos rutas absolutas basadas en
# esto para que el servidor funcione sin importar desde qué directorio se
# ejecute "python model.py" (antes, las rutas a los .pt eran relativas al
# directorio de trabajo y fallaban si no se lanzaba desde la raíz del repo).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------- IMPORTACIONES DE ML SEGURAS (FALLBACK) ----------------
# Antes existía una única bandera MOCK_MODE que mezclaba dos cosas distintas:
# el chatbot (LLM) y la visión artificial (YOLO). Esto provocaba que, por
# ejemplo, si "transformers" no estaba instalado, también se desactivaran las
# detecciones YOLO aunque "ultralytics" sí estuviera disponible. Ahora cada
# subsistema tiene su propia bandera y funcionan de forma independiente.
MOCK_LLM = False
MOCK_VISION = False
HAS_UNSLOTH = False
HAS_YOLO = False
HAS_PIL = False
HAS_TORCH = False

try:
    import torch
    import numpy as np
    from PIL import Image, ImageDraw
    HAS_PIL = True
    HAS_TORCH = True

    # Intentar importar transformers
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        logger.warning("Transformers no disponible. Se usará el chatbot en modo Simulación.")
        MOCK_LLM = True

    # Intentar importar unsloth (opcional)
    try:
        from unsloth import FastLanguageModel
        HAS_UNSLOTH = True
        logger.info("Unsloth detectado y listo para usar.")
    except ImportError:
        logger.info("Unsloth no disponible. Usando transformers estándar de Hugging Face.")
        HAS_UNSLOTH = False

    # Intentar importar ultralytics para YOLO
    try:
        from ultralytics import YOLO
        HAS_YOLO = True
        logger.info("Ultralytics/YOLO detectado y listo para usar.")
    except ImportError:
        logger.warning("Ultralytics no disponible. Las detecciones de visión correrán en modo Simulación.")
        HAS_YOLO = False
        MOCK_VISION = True

except ImportError as e:
    logger.warning(f"Librerías principales de ML (torch, numpy, PIL) no están completamente instaladas ({e}).")
    logger.warning("Iniciando el servidor en modo Simulación (LLM y visión).")
    MOCK_LLM = True
    MOCK_VISION = True

# ---------------- CONFIGURACIÓN DE MODELOS LLM ----------------
model = None
tokenizer = None
device = None
models = {}

if not MOCK_LLM:
    try:
        max_seq_length = 512
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        load_in_4bit = True if torch.cuda.is_available() else False
        model_name = os.environ.get("LLM_MODEL_NAME", "microsoft/Phi-3-mini-4k-instruct")

        logger.info("Cargando modelo LLM de agricultura...")
        if HAS_UNSLOTH:
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=model_name,
                max_seq_length=max_seq_length,
                dtype=dtype,
                load_in_4bit=load_in_4bit,
            )
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device)
        else:
            # Fallback a HuggingFace estándar
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            if torch.cuda.is_available():
                if load_in_4bit:
                    try:
                        from transformers import BitsAndBytesConfig
                        quant_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_compute_dtype=torch.float16,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_use_double_quant=True,
                        )
                        model = AutoModelForCausalLM.from_pretrained(
                            model_name, quantization_config=quant_config, device_map="auto"
                        )
                    except ImportError:
                        logger.warning(
                            "El paquete 'bitsandbytes' no está instalado; no se puede cargar en 4-bit. "
                            "Cargando en float16 completo (instala bitsandbytes con "
                            "'pip install bitsandbytes' para reducir el uso de VRAM)."
                        )
                        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16, device_map="auto")
                else:
                    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16, device_map="auto")
                device = torch.device("cuda")
            else:
                model = AutoModelForCausalLM.from_pretrained(model_name)
                device = torch.device("cpu")
                model.to(device)
        logger.info(f"LLM cargado exitosamente. CUDA disponible: {torch.cuda.is_available()} | Dispositivo usado: {device}")
        if not torch.cuda.is_available():
            logger.warning(
                "PyTorch no detecta GPU (CUDA no disponible). La inferencia correrá en CPU y será lenta. "
                "Si tienes una GPU NVIDIA, probablemente instalaste el build CPU-only de torch: "
                "reinstálalo con 'pip install torch --index-url https://download.pytorch.org/whl/cu121' "
                "(ajusta cu121 a la versión de CUDA que soporte tu driver)."
            )
    except Exception as e:
        logger.error(f"Error cargando el modelo LLM ({model_name}): {e}. Se habilita chatbot en modo simulación (usará la API de Hugging Face o respuestas locales como respaldo).")
        model = None
        tokenizer = None
else:
    logger.info("Modo Simulación de LLM activo. El chat usará la API de Hugging Face o respuestas locales predefinidas.")

# Cargar modelos YOLO (independiente del estado del LLM)
if HAS_YOLO and not MOCK_VISION:
    try:
        logger.info("Cargando modelos de visión YOLO...")
        models = {
            "deteccion_plagas": YOLO(os.path.join(BASE_DIR, "deteccion_plagas.pt")),
            "deteccion_enfermedades": YOLO(os.path.join(BASE_DIR, "deteccion_enfermedades.pt")),
            "plant_protect": YOLO(os.path.join(BASE_DIR, "plant_protect.pt")),
        }
        logger.info("Modelos YOLO cargados exitosamente.")
    except Exception as e:
        logger.error(f"Error cargando archivos de modelo YOLO (*.pt): {e}. Se usarán detecciones simuladas.")
        models = {}
else:
    logger.info("Modo Simulación de visión activo. Las detecciones YOLO serán simuladas.")

MOCK_MODE = MOCK_LLM

conversation_history = []
MAX_HISTORY = 6

# ---------------- DIBUJAR PREDICCIONES SIMULADAS (PILLOW) ----------------
def dibujar_caja_simulada(file_stream, label, box):
    try:
        file_stream.seek(0)
        img_bytes = file_stream.read()
        
        if not HAS_PIL:
            return base64.b64encode(img_bytes).decode()
            
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        
        x1 = box.get("x1", 50)
        y1 = box.get("y1", 50)
        x2 = box.get("x2", 180)
        y2 = box.get("y2", 180)
        
        if x2 > w or y2 > h:
            x1 = int(w * 0.2)
            y1 = int(h * 0.2)
            x2 = int(w * 0.7)
            y2 = int(h * 0.7)
            box["x1"] = x1
            box["y1"] = y1
            box["x2"] = x2
            box["y2"] = y2

        # Verde para saludable, rojo para enfermedad/plaga
        color = (16, 185, 129) if "saludable" in label.lower() else (239, 68, 68)
        
        # Dibujar borde grueso
        for offset in range(3):
            draw.rectangle([x1 - offset, y1 - offset, x2 + offset, y2 + offset], outline=color)
            
        # Dibujar fondo del texto
        draw.rectangle([x1, y1 - 22, x1 + 130, y1], fill=color)
        
        # Dibujar etiqueta (Pillow dibuja texto con fuente básica si no se pasa font)
        try:
            draw.text((x1 + 6, y1 - 18), label, fill=(255, 255, 255))
        except Exception:
            pass
            
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        logger.error(f"Error al dibujar caja simulada: {e}")
        file_stream.seek(0)
        return base64.b64encode(file_stream.read()).decode()

def dibujar_caja_simulada_base64(image_bytes, label, box):
    try:
        if not HAS_PIL:
            return base64.b64encode(image_bytes).decode()
            
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        
        # Escalar coordenadas basadas en 320x240 estándar de la webcam
        x1 = int(w * box.get("x1", 50) / 320.0) if w > 0 else 50
        y1 = int(h * box.get("y1", 50) / 240.0) if h > 0 else 50
        x2 = int(w * box.get("x2", 220) / 320.0) if w > 0 else 220
        y2 = int(h * box.get("y2", 220) / 240.0) if h > 0 else 220
        
        box["x1"] = x1
        box["y1"] = y1
        box["x2"] = x2
        box["y2"] = y2

        color = (16, 185, 129) if "saludable" in label.lower() else (239, 68, 68)
        
        for offset in range(3):
            draw.rectangle([x1 - offset, y1 - offset, x2 + offset, y2 + offset], outline=color)
            
        draw.rectangle([x1, y1 - 22, x1 + 120, y1], fill=color)
        try:
            draw.text((x1 + 6, y1 - 18), label, fill=(255, 255, 255))
        except Exception:
            pass
            
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        logger.error(f"Error al dibujar caja base64: {e}")
        return base64.b64encode(image_bytes).decode()


# ---------------- CHATBOT FALLBACK A REAL LLM (HUGGING FACE API) ----------------
def consultar_llm_api(prompt):
    # Intentar usar el API de Inferencia gratuito de HuggingFace para respuestas de IA reales
    try:
        api_url = "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-7B-Instruct"
        hf_token = os.environ.get("HF_TOKEN")
        headers = {}
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
            
        system_instructions = (
            "Eres un asistente agrícola experto. Responde en español de forma muy clara, concisa y profesional. "
            "Ayuda al agricultor con el control de plagas, riegos y cuidado de plantas."
        )
        
        payload = {
            "inputs": f"<|im_start|>system\n{system_instructions}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            "parameters": {
                "max_new_tokens": 250,
                "temperature": 0.7,
                "return_full_text": False
            }
        }
        
        # Realizamos petición web
        response = requests.post(api_url, headers=headers, json=payload, timeout=6)
        if response.status_code == 200:
            result = response.json()
            text = ""
            if isinstance(result, list) and len(result) > 0:
                text = result[0].get("generated_text", "").strip()
            elif isinstance(result, dict) and "generated_text" in result:
                text = result["generated_text"].strip()
                
            if text:
                if "<|im_end|>" in text:
                    text = text.split("<|im_end|>")[0]
                return text
    except Exception as e:
        logger.warning(f"Fallo al conectar con HuggingFace API: {e}. Usando respuestas simuladas locales.")
    
    # Fallback si no hay conexión o falla la API externa
    return obtener_respuesta_simulada(prompt)


def _contiene_palabra(texto, *palabras):
    """Coincidencia por palabra/frase completa (no substring). Evita falsos
    positivos como 'aguacate' disparando la palabra clave 'agua', o
    'aromas' disparando 'roya'."""
    for palabra in palabras:
        if re.search(r"\b" + re.escape(palabra) + r"\b", texto):
            return True
    return False


def buscar_respuesta_curada(prompt):
    """Devuelve una respuesta curada y verificada si el prompt coincide con un
    tema agrícola conocido (araña roja, mosca blanca, roya, etc.), o None si
    no hay coincidencia. Se usa tanto en modo simulación como ANTES de
    consultar el LLM real, para no depender de que un modelo genérico (que
    no fue entrenado en agricultura) "invente" contenido para temas donde ya
    tenemos una respuesta correcta preparada.
    """
    prompt_lower = prompt.lower().strip()

    if _contiene_palabra(prompt_lower, "temperatura", "calor", "frio", "frío"):
        return "🌡️ **Recomendación sobre Temperatura:** El rango óptimo para la mayoría de cultivos agrícolas (como solanáceas o leguminosas) está entre 18°C y 28°C. Si estás experimentando calor extremo (>35°C), se sugiere usar mallas de sombreado del 50%, aumentar la frecuencia de riego por goteo en horas frescas (madrugada/tarde) y ventilar adecuadamente los invernaderos para evitar estrés hídrico y aborto de flores."

    if _contiene_palabra(prompt_lower, "humedad", "riego", "agua"):
        return "💧 **Recomendación sobre Riego y Humedad:** La humedad en el suelo debe mantenerse en capacidad de campo (65-80% de humedad relativa del suelo). Un exceso de humedad combinado con calor propicia hongos de raíz (*Phytophthora*). Si la humedad ambiental es baja (<40%), incrementa riegos cortos y frecuentes para crear un microclima húmedo y evitar la sequedad foliar."

    if _contiene_palabra(prompt_lower, "araña roja", "arana roja"):
        return "🕷️ **Control de Araña Roja (*Tetranychus urticae*):** Este ácaro succionador de savia aparece en ambientes cálidos y secos. Genera telarañas finas en el envés. \n*Tratamiento ecológico:* Pulveriza agua para elevar la humedad, aplica jabón potásico combinado con aceite de neem (5ml/L) cada 3 días por el envés de las hojas."

    if _contiene_palabra(prompt_lower, "mosca blanca"):
        return "🪰 **Control de Mosca Blanca:** Se alimentan de la savia y secretan melaza que atrae el hongo de la negrilla.\n*Soluciones:* Coloca trampas cromáticas amarillas impregnadas de pegamento o aceite de cocina para captura masiva. Trata con infusión de ajo o jabón potásico para disolver la capa protectora del insecto."

    if _contiene_palabra(prompt_lower, "roya"):
        return "🍂 **Control de Roya (Hongo):** Se caracteriza por pústulas de color marrón-anaranjado en las hojas.\n*Tratamiento:* Elimina de inmediato las hojas infectadas y quémalas (no las dejes en la composta). Aplica un fungicida preventivo a base de cobre (caldo bordelés) o extracto de cola de caballo para fortalecer la pared celular de la planta."

    if _contiene_palabra(prompt_lower, "enferma", "enfermedad", "manchas", "plaga"):
        return "🌱 **Diagnóstico de Salud Foliar:** Las anomalías en el follaje suelen deberse a hongos, virus o deficiencias de nutrientes. Retira las hojas afectadas. Mantén una buena separación de plantas para favorecer la ventilación y aplica preventivos como silicato de potasio o trichoderma en el suelo."

    if _contiene_palabra(prompt_lower, "hola", "buenos dias", "buenos días", "saludos"):
        return "¡Hola! Soy tu Asistente Agrícola Inteligente. ¿Cómo van tus cultivos hoy? Puedes preguntarme sobre control de plagas, manejo de riego, rangos de temperatura ideales o subir una foto de tus hojas para que las analice."

    return None


def obtener_respuesta_simulada(prompt):
    respuesta_curada = buscar_respuesta_curada(prompt)
    if respuesta_curada:
        return respuesta_curada
    return f"🌾 Como tu asesor agrícola, entiendo que consultas sobre: **'{prompt}'**. Te sugiero monitorear regularmente las hojas de tu cultivo, vigilar que los niveles de humedad en suelo no bajen del 40%, y mantener una temperatura constante en torno a los 24°C. Si notas decoloración o insectos, indícamelo para formular un tratamiento adecuado."

def generar_respuesta(prompt, max_new_tokens=300):
    global conversation_history
    conversation_history.append({"role": "user", "content": prompt})

    while len(conversation_history) > MAX_HISTORY:
        conversation_history.pop(0)

    respuesta_curada = buscar_respuesta_curada(prompt)
    if respuesta_curada:
        conversation_history.append({"role": "assistant", "content": respuesta_curada})
        return respuesta_curada

    # Si está en modo simulación o el modelo LLM no cargó
    if MOCK_MODE or model is None or tokenizer is None:
        respuesta = consultar_llm_api(prompt)
        conversation_history.append({"role": "assistant", "content": respuesta})
        return respuesta

    # Inferencia real con el LLM cargado
    try:
        system_prompt = (
            "Eres un asistente agrícola experto. Respondes ÚNICAMENTE en español "
            "correcto y natural (nunca en inglés ni mezclando idiomas), de forma "
            "clara, breve y en frases completas. No inventes palabras. "
            "Si te preguntan sobre un tema del que no estás seguro o que no es "
            "agrícola, dilo honestamente en vez de inventar una respuesta."
        )
        if getattr(tokenizer, "chat_template", None):
            mensajes = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            formatted_prompt = tokenizer.apply_chat_template(
                mensajes, tokenize=False, add_generation_prompt=True
            )
        else:
            formatted_prompt = (
                "### Instruction:\n"
                f"{system_prompt}\n\n"
                f"### Input:\n{prompt}\n\n"
                "### Response:\n"
            )

        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(device)

        _t0 = time.time()
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                repetition_penalty=1.1,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.eos_token_id,
            )
        _elapsed = time.time() - _t0
        _n_generated = output_ids.shape[-1] - inputs["input_ids"].shape[-1]
        logger.info(
            f"Generación LLM: {_n_generated} tokens en {_elapsed:.1f}s "
            f"({_n_generated / _elapsed:.1f} tokens/s)"
        )

        generated_ids = output_ids[:, inputs["input_ids"].shape[-1]:]
        respuesta = tokenizer.decode(generated_ids[0], skip_special_tokens=True).strip()
        conversation_history.append({"role": "assistant", "content": respuesta})
        return respuesta
    except Exception as e:
        logger.error(f"Error durante inferencia de LLM: {e}. Usando fallback de API.")
        return consultar_llm_api(prompt)

# ---------------- CONFIGURACIÓN GENERAL ----------------
ESP32_IP = os.environ.get("ESP32_IP", "http://192.168.1.139")

app = Flask(__name__, static_folder='public')
CORS(app)

# ---------------- HELPER DETECCIONES ----------------
def extraer_detecciones(results):
    detections = []
    if results[0].boxes is None:
        return detections
    boxes = results[0].boxes
    for i in range(len(boxes)):
        cls_id = int(boxes.cls[i].item())
        conf_val = round(float(boxes.conf[i].item()), 3)
        detections.append({
            "name": results[0].names[cls_id],
            "confidence": conf_val,
            "conf": conf_val,  # Soportar ambas llaves (frontend/backend)
            "box": {
                "x1": round(float(boxes.xyxy[i][0].item()), 2),
                "y1": round(float(boxes.xyxy[i][1].item()), 2),
                "x2": round(float(boxes.xyxy[i][2].item()), 2),
                "y2": round(float(boxes.xyxy[i][3].item()), 2),
            }
        })
    return detections

# ---------------- RUTAS API ----------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(app.static_folder, path)

@app.route("/api/sensores")
def api_sensores():
    try:
        respuesta = requests.get(f"{ESP32_IP}/datos", timeout=2)
        return respuesta.json()
    except Exception as e:
        # Ya no se devuelven datos ficticios. Lanza error 500 para indicar desconexión real en la interfaz.
        return jsonify({"error": "No se pudo conectar al ESP32"}), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        pregunta = data.get("pregunta", "")
        if not pregunta:
            return jsonify({"respuesta": "No se proporcionó una pregunta."}), 400
        logger.info(f"Pregunta recibida: {pregunta}")
        respuesta = generar_respuesta(pregunta)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        logger.error(f"Error en /chat: {e}")
        return jsonify({"respuesta": "Error al procesar la pregunta."}), 500

@app.route("/predict", methods=["POST"])
def predict():
    try:
        model_name = request.form.get("model")
        file = request.files.get("image")

        if not model_name:
            return jsonify({"error": "Modelo YOLO no especificado."}), 400
        if not file:
            return jsonify({"error": "Imagen no proporcionada."}), 400

        # Si estamos en modo simulación o el modelo particular no está cargado
        if MOCK_VISION or model_name not in models:
            logger.info(f"Modo simulación de visión: simulando análisis para {model_name}")
            
            box = {}
            name = "hoja saludable"
            conf_val = 0.85
            
            if model_name == "deteccion_plagas":
                name = "araña roja"
                conf_val = 0.88
                box = {"x1": 50, "y1": 50, "x2": 180, "y2": 180}
            elif model_name == "deteccion_enfermedades":
                name = "roya"
                conf_val = 0.91
                box = {"x1": 70, "y1": 60, "x2": 210, "y2": 200}
            else:  # plant_protect
                name = "hoja enferma"
                conf_val = 0.79
                box = {"x1": 30, "y1": 40, "x2": 240, "y2": 220}
                
            label = f"{name} [{int(conf_val*100)}%]"
            
            # Dibujar la caja directamente sobre la imagen subida
            encoded_img = dibujar_caja_simulada(file, label, box)
            
            detections = [
                {
                    "name": name,
                    "confidence": conf_val,
                    "conf": conf_val,
                    "box": box
                }
            ]
            
            nombres_unicos = list(dict.fromkeys([d["name"] for d in detections]))
            descripcion_texto = "¿Qué es " + " y ".join(nombres_unicos) + "?"

            return jsonify({
                "image": encoded_img,
                "detections": detections,
                "descripcion_texto": descripcion_texto
            })

        # Predicción real con YOLO
        if model_name == "plant_protect":
            temp_dir = tempfile.gettempdir()
            temp_filename = f"{uuid.uuid4()}.jpg"
            temp_image_path = os.path.join(temp_dir, temp_filename)
            file.save(temp_image_path)

            results = models[model_name].predict(
                source=temp_image_path,
                conf=0.3,
                save=True,
                project=temp_dir,
                name='deteccion_hoja',
                exist_ok=True
            )

            saved_path = os.path.join(temp_dir, 'deteccion_hoja', os.path.basename(temp_image_path))
            with open(saved_path, "rb") as f:
                encoded_img = base64.b64encode(f.read()).decode()

            detections = extraer_detecciones(results)
        else:
            img_bytes = file.read()
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img_np = np.array(image)

            results = models[model_name].predict(image)
            annotated_img = results[0].plot(img=img_np)

            buffered = io.BytesIO()
            Image.fromarray(annotated_img).save(buffered, format="JPEG")
            encoded_img = base64.b64encode(buffered.getvalue()).decode()

            detections = extraer_detecciones(results)

        if detections:
            nombres_raw = [d.get("name", "objeto").lower() for d in detections]
            correcciones = {
                "arana roja": "araña roja",
                "mosca blanca": "mosca blanca",
                "roya": "roya",
            }
            nombres_corregidos = [correcciones.get(n, n) for n in nombres_raw]
            nombres_unicos = list(dict.fromkeys(nombres_corregidos))
            descripcion_texto = "¿Qué es " + " y ".join(nombres_unicos) + "?"
        else:
            descripcion_texto = "No se detectaron objetos."

        return jsonify({
            "image": encoded_img,
            "detections": detections,
            "descripcion_texto": descripcion_texto
        })

    except Exception as e:
        logger.error(f"Error en /predict: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/predict_stream", methods=["POST"])
def predict_stream():
    try:
        model_name = request.form.get("model")
        if model_name != "plant_protect":
            return jsonify({"error": "Solo plant_protect es compatible con streaming."}), 400

        image_data = request.form.get("image")
        if not image_data:
            return jsonify({"error": "No se proporcionó una imagen."}), 400

        image_data = image_data.split(",")[1]
        img_bytes = base64.b64decode(image_data)

        # Si estamos en modo simulación
        if MOCK_VISION or "plant_protect" not in models:
            import random
            conf_val = round(random.uniform(0.78, 0.94), 2)
            name = "hoja saludable" if random.random() > 0.4 else "hoja enferma"
            box = {"x1": 50, "y1": 50, "x2": 220, "y2": 220}
            
            label = f"{name} [{int(conf_val*105)}%]"
            encoded_img = dibujar_caja_simulada_base64(img_bytes, label, box)
            
            detections = [
                {
                    "name": name,
                    "confidence": conf_val,
                    "conf": conf_val,
                    "box": box
                }
            ]
            return jsonify({
                "image": encoded_img,
                "detections": detections
            })

        # Procesar frame real
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        temp_dir = tempfile.gettempdir()
        temp_filename = f"{uuid.uuid4()}.jpg"
        temp_image_path = os.path.join(temp_dir, temp_filename)
        image.save(temp_image_path)

        results = models[model_name].predict(
            source=temp_image_path,
            conf=0.25,
            save=True,
            project=temp_dir,
            name='deteccion_hoja',
            exist_ok=True
        )

        saved_path = os.path.join(temp_dir, 'deteccion_hoja', os.path.basename(temp_image_path))
        with open(saved_path, "rb") as f:
            encoded_img = base64.b64encode(f.read()).decode()

        detections = extraer_detecciones(results)
        return jsonify({"image": encoded_img, "detections": detections})

    except Exception as e:
        logger.error(f"Error en /predict_stream: {e}")
        return jsonify({"error": str(e)}), 500

# ---------------- INICIAR FLASK ----------------
if __name__ == "__main__":
    port = 8000
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
