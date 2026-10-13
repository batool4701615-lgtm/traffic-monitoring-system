   FROM python:3.12-slim

   # System libraries OpenCV needs
   RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
       && rm -rf /var/lib/apt/lists/*

   WORKDIR /app

   # CPU-only PyTorch keeps the image much smaller
   RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY . .

   # Download the YOLO weights into the folder the app reads from
   RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" && mv yolov8n.pt backend/models/

   # Folders the app writes to at runtime
   RUN mkdir -p videos outputs data && chmod -R 777 videos outputs data

   EXPOSE 7860
   CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]