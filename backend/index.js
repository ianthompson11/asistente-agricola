const express = require("express");
const path = require("path");
const proxy = require("express-http-proxy");

const app = express();
const PORT = 3000;
const FLASK_URL = "http://localhost:8000";

// Servir archivos estáticos del frontend
app.use(express.static(path.join(__dirname, "public")));

// 👉 Si alguien accede a "/" devuelve index.html automáticamente
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

// Proxy para las peticiones de chat
app.use("/chat", proxy(FLASK_URL, {
  proxyReqPathResolver: () => "/chat"
}));

// Proxy para predicciones YOLO de imágenes subidas (admite multipart/form-data automáticamente)
app.use("/predict", proxy(FLASK_URL, {
  proxyReqPathResolver: () => "/predict"
}));

// Proxy para streaming en tiempo real de webcam
app.use("/predict_stream", proxy(FLASK_URL, {
  proxyReqPathResolver: () => "/predict_stream"
}));

// Proxy para la API de sensores
app.use("/api/sensores", proxy(FLASK_URL, {
  proxyReqPathResolver: () => "/api/sensores"
}));

app.listen(PORT, () => {
  console.log(`Servidor Express escuchando en http://localhost:${PORT}`);
  console.log(`Redirigiendo APIs hacia Flask en ${FLASK_URL}`);
});