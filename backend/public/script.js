// script.js

const baseURL = window.location.origin;
let stream = null;

// ACTUALIZAR SENSORES Y REALIZAR PREDICCIONES DE SALUD AUTOMÁTICAS
// ACTUALIZAR SENSORES Y REALIZAR PREDICCIONES DE SALUD AUTOMÁTICAS
async function actualizarSensores() {
  try {
    const res = await fetch(`${baseURL}/api/sensores`);
    if (!res.ok) {
      throw new Error("ESP32 desconectado o error en el servidor");
    }
    const data = await res.json();
    
    const tempEl = document.getElementById("temp");
    const humEl = document.getElementById("hum");
    const lightEl = document.getElementById("light");
    
    if (tempEl) tempEl.textContent = data.temperatura ?? "--";
    if (humEl) humEl.textContent = data.humedad ?? "--";
    if (lightEl) lightEl.textContent = data.luz ?? "--";

    actualizarAguja("tempNeedle", data.temperatura, 0, 45);
    actualizarAguja("humNeedle", data.humedad, 0, 100);
    actualizarAguja("lightNeedle", data.luz, 0, 100);

    // Evaluar estado automáticamente
    evaluarSaludCultivo(data.temperatura, data.humedad);
  } catch (error) {
    console.error("No se pudieron obtener datos del ESP32:", error);
    const tempEl = document.getElementById("temp");
    const humEl = document.getElementById("hum");
    const lightEl = document.getElementById("light");
    
    if (tempEl) tempEl.textContent = "--";
    if (humEl) humEl.textContent = "--";
    if (lightEl) lightEl.textContent = "--";
    
    evaluarSaludCultivo(undefined, undefined);
  }
}

// AGUJAS DE LOS MEDIDORES (temperatura / humedad / luz)
function actualizarAguja(id, valor, min, max) {
  const needle = document.getElementById(id);
  if (!needle) return;
  const num = parseFloat(valor);
  if (isNaN(num)) {
    needle.style.transform = "rotate(0deg)";
    return;
  }
  const clamped = Math.min(max, Math.max(min, num));
  const pct = (clamped - min) / (max - min);
  const angle = -90 + pct * 180;
  needle.style.transform = `rotate(${angle}deg)`;
}

// EVALUACIÓN DE SALUD AUTOMÁTICA EN BASE A SENSORES
function evaluarSaludCultivo(temp, hum) {
  const estadoSaludText = document.getElementById("estadoSaludText");
  const estadoSaludCard = document.getElementById("estadoSaludCard");

  if (!estadoSaludText) return;

  if (temp === undefined || temp === null || hum === undefined || hum === null) {
    estadoSaludText.innerHTML = "<strong>ESP32 desconectado:</strong> no se detecta señal del módulo de sensores físico.";
    if (estadoSaludCard) {
      estadoSaludCard.className = "p-3.5 rounded-lg bg-white/70 border border-[#c23b2e]/40 text-[#c23b2e] text-sm";
    }
    return;
  }

  let mensaje = "<strong>Estado óptimo:</strong> el cultivo cuenta con condiciones saludables de clima.";
  let colorClass = "border-[#2f7b4f]/25 text-[#1f2b24]";

  if (temp < 18 || temp > 32) {
    mensaje = `<strong>Estrés térmico:</strong> temperatura fuera de rango óptimo (${temp}°C). Se sugiere ventilación o sombreado.`;
    colorClass = "border-[#c98a2e]/40 text-[#8a5f1f]";
  } else if (hum < 45) {
    mensaje = `<strong>Estrés hídrico:</strong> humedad baja (${hum}%). Considera activar el riego para rehidratar el suelo.`;
    colorClass = "border-[#3e7c99]/40 text-[#2c5a70]";
  } else if (hum > 85) {
    mensaje = `<strong>Riesgo de hongos:</strong> humedad excesiva (${hum}%). Suspende riegos y asegura ventilación.`;
    colorClass = "border-[#c23b2e]/40 text-[#c23b2e]";
  }

  estadoSaludText.innerHTML = mensaje;
  if (estadoSaludCard) {
    estadoSaludCard.className = `p-3.5 rounded-lg bg-white/70 border text-sm ${colorClass}`;
  }
}

// RECOMENDAR ACCIONES (Interactivo)
function recomendarAccion() {
  const tempText = document.getElementById("temp")?.textContent;
  const humText = document.getElementById("hum")?.textContent;
  const temp = parseFloat(tempText);
  const hum = parseFloat(humText);

  let mensaje = "✅ Las mediciones de los sensores indican que no se requieren acciones inmediatas.";
  if (isNaN(temp) || isNaN(hum)) {
    alert("Esperando datos de sensores para formular recomendaciones.");
    return;
  }

  if (hum < 45) {
    mensaje = "💧 <strong>Recomendación Agrícola:</strong> Se detecta baja humedad. Se recomienda programar riego por goteo durante 25 minutos en las primeras horas del día para maximizar absorción.";
  } else if (temp > 32) {
    mensaje = "🌡️ <strong>Recomendación Agrícola:</strong> Temperatura elevada. Se sugiere extender mallas de sombreado y habilitar nebulizadores para bajar la temperatura de las hojas.";
  } else if (hum > 85) {
    mensaje = "💨 <strong>Recomendación Agrícola:</strong> Humedad saturada. Se aconseja suspender riegos programados y despejar maleza baja para propiciar corriente de aire.";
  }
  
  agregarMensajeChat("Asistente", mensaje);
}

// ASISTENTE DE VOZ (Speech Synthesis)
function hablarConAsistente() {
  const temp = parseFloat(document.getElementById("temp")?.textContent);
  const hum = parseFloat(document.getElementById("hum")?.textContent);

  let mensaje = "Hola agricultor, tus cultivos están en buen estado en este momento.";
  if (hum < 45) {
    mensaje = "Hola agricultor, considera regar tus cultivos pronto debido a que la humedad está baja.";
  } else if (temp > 32) {
    mensaje = "Hola agricultor, protege tus cultivos del exceso de calor desplegando mallas de sombra.";
  } else if (hum > 85) {
    mensaje = "Hola agricultor, reduce el riego y ventila el área para prevenir enfermedades por hongos.";
  }

  const speech = new SpeechSynthesisUtterance(mensaje);
  speech.lang = "es-ES";
  window.speechSynthesis.speak(speech);
  
  agregarMensajeChat("Asistente (Voz)", mensaje);
}

// MOSTRAR VISTA PREVIA
function mostrarImagen(event) {
  const vista = document.getElementById("vistaPrevia");
  const uploadPlaceholder = document.getElementById("uploadPlaceholder");
  
  if (event.target.files && event.target.files[0]) {
    vista.src = URL.createObjectURL(event.target.files[0]);
    vista.classList.remove("hidden");
    if (uploadPlaceholder) uploadPlaceholder.classList.add("hidden");
  } else {
    vista.classList.add("hidden");
    if (uploadPlaceholder) uploadPlaceholder.classList.remove("hidden");
  }
}

// ENVIAR IMAGEN A YOLO
async function enviarYOLO() {
  const inputFile = document.getElementById("inputImagen");
  const modelo = document.getElementById("modeloVision").value;
  const imagenResultado = document.getElementById("imagenResultado");
  const resultPlaceholder = document.getElementById("resultPlaceholder");
  const deteccionesBox = document.getElementById("detecciones");
  const resultadoText = document.getElementById("resultado");

  if (!inputFile.files.length) {
      alert("Por favor, selecciona una imagen primero.");
      return;
  }

  const formData = new FormData();
  formData.append("model", modelo);
  formData.append("image", inputFile.files[0]);

  try {
      if (resultadoText) {
          resultadoText.classList.remove("hidden", "text-transparent");
          resultadoText.textContent = "⌛ Analizando imagen con modelo de visión...";
      }
      
      const res = await fetch(`${baseURL}/predict`, {
          method: "POST",
          body: formData,
      });
      const data = await res.json();

      if (data.error) {
          if (resultadoText) {
              resultadoText.textContent = `Error: ${data.error}`;
          }
          return;
      }

      // Mostrar imagen anotada (y ocultar el placeholder "Esperando imagen...")
      if (imagenResultado) {
          imagenResultado.src = `data:image/jpeg;base64,${data.image}`;
          imagenResultado.classList.remove("hidden");
      }
      if (resultPlaceholder) {
          resultPlaceholder.classList.add("hidden");
      }

      // Mostrar detecciones en JSON
      if (deteccionesBox) {
          deteccionesBox.textContent = JSON.stringify(data.detections, null, 2);
          deteccionesBox.classList.remove("hidden");
      }

      // Mostrar resultado en texto
      const desc = data.descripcion_texto || "Análisis completado.";
      if (resultadoText) {
          resultadoText.textContent = desc;
      }

      // Rellenar caja de entrada de chat
      const userInput = document.getElementById("userInput");
      if (userInput && data.descripcion_texto) {
          userInput.value = data.descripcion_texto;
      }

  } catch (error) {
      console.error("Error al enviar imagen:", error);
      if (resultadoText) {
          resultadoText.textContent = "❌ Error al establecer contacto con el servidor de análisis.";
      }
  }
}

// ENVIAR PREGUNTA AL LLM
async function enviarPregunta() {
  const input = document.getElementById("userInput");
  const pregunta = input.value.trim();
  if (pregunta === "") return;

  input.value = "";
  agregarMensajeChat("Tú", pregunta);

  try {
    const respuesta = await fetch(`${baseURL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ pregunta: pregunta }),
    });

    const data = await respuesta.json();
    const output = data.respuesta || "[sin respuesta]";
    agregarMensajeChat("Asistente", output);
  } catch (err) {
    console.error("Error al obtener respuesta:", err);
    agregarMensajeChat("Asistente", "❌ Error al obtener respuesta del servidor.");
  }
}

// ACTIVAR RECONOCIMIENTO DE VOZ
async function activarVoz() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
      alert("El navegador actual no es compatible con el reconocimiento de voz.");
      return;
  }

  const reconocimiento = new SpeechRecognition();
  reconocimiento.lang = "es-ES";
  
  const micBtn = document.getElementById("micBtn");
  if (micBtn) {
      micBtn.innerHTML = '<i class="fas fa-dot-circle text-[#c23b2e] mr-1"></i> Grabando...';
      micBtn.classList.add("text-[#c23b2e]");
  }

  reconocimiento.onresult = function(event) {
      const texto = event.results[0][0].transcript;
      const userInput = document.getElementById("userInput");
      if (userInput) {
          userInput.value = texto;
      }
      enviarPregunta();
  };

  reconocimiento.onerror = function(event) {
      console.error("Error de reconocimiento de voz:", event.error);
      restaurarBotonMic();
  };

  reconocimiento.onend = function() {
      restaurarBotonMic();
  };

  reconocimiento.start();
}

function restaurarBotonMic() {
  const micBtn = document.getElementById("micBtn");
  if (micBtn) {
      micBtn.innerHTML = '<i class="fas fa-microphone"></i>';
      micBtn.classList.remove("text-[#c23b2e]");
  }
}

// WEBCAM STREAM EN TIEMPO REAL
async function startWebcam() {
  try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error("API getUserMedia no soportada.");
      }
      
      try {
          stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: "environment" }
          });
      } catch (rearError) {
          console.warn("Cámara trasera no accesible, usando la frontal:", rearError);
          stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: "user" }
          });
      }
      
      const video = document.getElementById('webcam');
      if (video) {
          video.srcObject = stream;
          video.classList.remove("hidden");
      }
      
      document.getElementById('webcamPlaceholder')?.classList.add('hidden');
      document.getElementById('startWebcam')?.classList.add('hidden');
      document.getElementById('stopWebcam')?.classList.remove('hidden');
      // annotatedFrame se muestra recién cuando llegue el primer frame
      // procesado (ver processFrame); mientras tanto se ve el video crudo.
      
      console.log("Webcam inicializada correctamente.");
      processFrame();
  } catch (error) {
      console.error("Error al iniciar webcam:", error);
      const rtResult = document.getElementById('realtimeResult');
      if (rtResult) {
          rtResult.innerHTML = `<span class="text-[#c23b2e] text-sm">Error: cámara no disponible o requiere permisos.</span>`;
      }
  }
}

function stopWebcam() {
  if (stream) {
      stream.getTracks().forEach(track => track.stop());
      stream = null;
      
      const video = document.getElementById('webcam');
      if (video) {
          video.srcObject = null;
          video.classList.add("hidden");
      }
      
      const annotated = document.getElementById('annotatedFrame');
      if (annotated) {
          annotated.src = '';
          annotated.classList.add("hidden");
      }
      
      document.getElementById('startWebcam')?.classList.remove('hidden');
      document.getElementById('stopWebcam')?.classList.add('hidden');
      document.getElementById('webcamPlaceholder')?.classList.remove('hidden');
      
      const rtResult = document.getElementById('realtimeResult');
      if (rtResult) rtResult.textContent = "";
  }
}

async function processFrame() {
  if (!stream) return;
  
  const video = document.getElementById('webcam');
  const canvas = document.getElementById('canvas');
  if (!video || !canvas) return;

  const context = canvas.getContext('2d');
  canvas.width = video.videoWidth || 320;
  canvas.height = video.videoHeight || 240;
  
  if (canvas.width > 0 && canvas.height > 0) {
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      
      const formData = new FormData();
      formData.append('image', canvas.toDataURL('image/jpeg', 0.6));
      formData.append('model', 'plant_protect');

      try {
          const response = await fetch(`${baseURL}/predict_stream`, {
              method: 'POST',
              body: formData
          });
          const result = await response.json();
          
          if (result.error) {
              console.error("Error en predict_stream:", result.error);
          } else if (result.image) {
              const annotatedFrame = document.getElementById('annotatedFrame');
              if (annotatedFrame) {
                  annotatedFrame.src = `data:image/jpeg;base64,${result.image}`;
                  annotatedFrame.classList.remove("hidden");
              }
              
              const rtResult = document.getElementById('realtimeResult');
              if (rtResult) {
                  if (result.detections && result.detections.length > 0) {
                      const detText = result.detections.map(d => {
                          const conf = d.conf || d.confidence || 0;
                          return `${d.name} (${Math.round(conf * 100)}%)`;
                      }).join(', ');
                      rtResult.innerHTML = `Detecciones: <span class="text-[#2f7b4f] font-semibold">${detText}</span>`;
                  } else {
                      rtResult.innerHTML = `<span class="text-[#445048] text-sm">Escaneando follaje en vivo...</span>`;
                  }
              }
          }
      } catch (error) {
          console.error("Error al procesar frame de webcam:", error);
      }
  }

  if (stream) {
      setTimeout(processFrame, 400); // 2.5 FPS
  }
}

// HELPER: AGREGAR MENSAJE AL CHAT
function agregarMensajeChat(remitente, texto) {
  const chat = document.getElementById("chatBox");
  if (!chat) return;

  const isUser = remitente === "Tú";
  const alignClass = isUser ? "justify-end" : "justify-start";
  const bgClass = isUser
      ? "bg-[#2f7b4f] text-white rounded-tr-none"
      : "bg-white/90 text-[#1f2b24] border border-white/70 rounded-tl-none";
  const labelClass = isUser ? "text-white/80" : "text-[#2f7b4f]";

  const messageHtml = `
    <div class="flex ${alignClass} mb-3">
      <div class="max-w-[85%] ${bgClass} rounded-xl px-4 py-2.5 text-sm leading-relaxed">
        <div class="text-[10px] font-semibold mb-1 ${labelClass}">${remitente}</div>
        <div>${texto}</div>
      </div>
    </div>
  `;
  
  chat.innerHTML += messageHtml;
  chat.scrollTop = chat.scrollHeight;
}

// INICIALIZACIÓN
document.addEventListener("DOMContentLoaded", () => {
  setInterval(actualizarSensores, 5000);
  actualizarSensores();

  // Escuchar tecla Enter
  const userInput = document.getElementById("userInput");
  if (userInput) {
      userInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
              enviarPregunta();
          }
      });
  }
});
