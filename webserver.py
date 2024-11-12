import os
import sys
import json

from flask import Flask, flash, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

from PIL import Image
import numpy as np
import torch
from torchvision.models import resnet50
from torchvision import transforms
import plotly.graph_objs as go

# curl -X POST http://127.0.0.1:5000/upload -F "frame=@/home/tenzing/Pictures/flower2.jpg"
# op de client run: sudo python3 run.py resnet50_retrained_grass_flower.rknn 0

# Constants
CHECKPOINT_PATH = 'models/resnet50_weights_best_acc.tar'  
NUM_CLASSES = 1081  # Number of classes for the Pl@ntNet-300K dataset
SLIDING_WINDOW_SIZE = 20 # Number of frames to keep in the sliding window
UPLOAD_FOLDER = 'frames' # Folder to store the uploaded frames

# Flask App and Global Variables
app = Flask(__name__)
model = None
toggle_samples = False
embeddings, class_names = [], [] 
class_color = {0: 'red', 1: 'green'} # Color for each class
length_initial_embeddings = 0

def clear_directory(directory_path):
    """Remove all files in the specified directory."""
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
                print(f'Deleted: {file_path}')
            except Exception as e:
                print(f'Error deleting {file_path}: {e}')
                
def initialize_model():
    """Load and initialize the ResNet-50 model."""
    model = resnet50(num_classes=NUM_CLASSES)
    model = torch.nn.Sequential(*list(model.children())[:-1])  # Remove final classification layer
    
    try:
        checkpoint = torch.load(CHECKPOINT_PATH, map_location='cpu', weights_only=True)
        state_dict = {k.replace('module.', ''): v for k, v in checkpoint.get('state_dict', checkpoint).items()}
        model.load_state_dict(state_dict, strict=False)
        model.eval()
        print("Checkpoint loaded successfully.")
        return model

    except Exception as e:
        print(f"Error loading checkpoint: {e}")
        exit(1)
        
    return model

def encode_image(input_tensor):
    """Generate embeddings from an image tensor using the PlantNet model."""
    with torch.no_grad():
        return model(input_tensor).cpu().numpy().flatten()

def preprocess_image(image):
    """Preprocess an image for ResNet-50."""
    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    return transform(image).unsqueeze(0)  # Add batch dimension
        
def load_image(img_path, target_size=None):
    """Load and optionally resize an image for embedding visualization."""
    img = Image.open(img_path)
    if target_size:
        img = img.resize(target_size)
    return np.array(img)
        
def visualize_embeddings_2d(embeddings, samples_vis=False):
    """Visualize 2D embeddings using PCA and Matplotlib."""
    features = pca.transform(embeddings)  # Transform the embeddings using PCA
    plt.figure(figsize=(10, 10))
    
    def add_thumbnail(image_path, x, y, frame_color=None):
        """Add thumbnail images to plot points."""
        try:
            plt.scatter(x, y, alpha=0)  # Hide the original points
            img = load_image(image_path, target_size=(60, 60))
            imagebox = OffsetImage(img, zoom=0.8)
            ab = AnnotationBbox(imagebox, (x, y), frameon=bool(frame_color), pad=0.1, bboxprops=dict(edgecolor=frame_color, linewidth=2) if frame_color else None)
            plt.gca().add_artist(ab)
        except Exception as e:
            print(f"Error loading image {image_path}: {e}")
    
    # Inital embeddings are the samples
    if samples_vis:
        sample_files = sorted(os.listdir("samples"), key=lambda x: int(x.split('.')[0]))
        print(f"Initial embeddings length: {length_embeddings}, Sample files length: {len(sample_files)}")

        for idx, point in enumerate(features[:length_embeddings]):
            add_thumbnail(os.path.join("samples", sample_files[idx]), point[0], point[1])

    # Add new frames to the plot
    frame_files = sorted(os.listdir(UPLOAD_FOLDER), key=lambda x: int(x.split('.')[0]))
    print("Images in frames directory: ", frame_files)
    if frame_files != []:
        for idx, point in enumerate(features[length_embeddings:]):
            frame_color = class_color.get(class_names[idx] if idx == len(features[length_embeddings:]) - 1 else None)
            add_thumbnail(os.path.join(UPLOAD_FOLDER, frame_files[idx]), point[0], point[1], frame_color)
        
    plt.title("Image Embeddings")
    plt.xlabel("Dimension 1")
    plt.ylabel("Dimension 2")
    plt.autoscale(True)
    plt.grid()
    plt.savefig(os.path.join('static/images', 'embeddings_plot.png'))
    plt.close()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/toggle", methods=['POST'])
def toggle():
    global toggle_samples, embeddings
    toggle_samples = not toggle_samples
    print(f"Toggle samples: {toggle_samples}")
    visualize_embeddings_2d(embeddings, samples_vis=toggle_samples)
    return redirect(url_for('home'))   

@app.route('/upload', methods=['POST'])
def upload():
    if 'frame' not in request.files:
        return "No file part", 400
    
    global embeddings, class_names, toggle_samples
    frame = request.files['frame']
    class_name = int(request.form['class']) # Get the class name from the form
    filename = f"{len(embeddings)-length_embeddings}.jpg" # Save the frame with a unique name
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    frame.save(filepath)
    class_names.append(class_name)
    
    frame = Image.open(filepath)
    image_tensor = preprocess_image(frame)
    embeddings.append(encode_image(image_tensor))
    
    # Check if the sliding window size is reached
    if len(embeddings) > (length_embeddings + SLIDING_WINDOW_SIZE): 
        oldest_frame = sorted(os.listdir(UPLOAD_FOLDER), key=lambda x: int(x.split('.')[0]))[0] # Remove oldest from frames directory
        os.remove(os.path.join(UPLOAD_FOLDER, oldest_frame)) # Remove oldest from frames directory
        print(f"Removed oldest frame: {oldest_frame}")
        embeddings.pop(length_embeddings) # Remove oldest from embeddings list
        class_names.pop(0) # Remove oldest from class names list
        
    visualize_embeddings_2d(embeddings, samples_vis=toggle_samples) 
    return redirect(url_for('home'))       

@app.route('/reset', methods=['POST'])
def reset():
    global embeddings, class_names
    
    if len(embeddings) == length_embeddings:
        print("Nothing to reset.")
        return redirect(url_for('home'))
    
    # Resetting the embeddings and class names
    print(f"Resizing embeddings vector with length {len(embeddings)}, to initial length of {length_embeddings}.")
    embeddings = embeddings[:length_embeddings]
    class_names = []
    clear_directory(UPLOAD_FOLDER) # Clear directory of frames
    visualize_embeddings_2d(embeddings, samples_vis=toggle_samples) 
    return redirect(url_for('home'))       

if __name__ == "__main__":
    model = initialize_model() # Load the PlantNet model and weights
    pca = PCA(n_components=2)

    # Load embeddings from JSON file for visualization
    with open("embeddings.json", 'r') as json_file:
        sample_data = json.load(json_file)
    embeddings = [item['feature'] for item in sample_data]
    
    pca.fit(embeddings) # Fit PCA on the embeddings
    length_embeddings = len(embeddings) # Initial length of embeddings
        
    clear_directory(UPLOAD_FOLDER) # Remove intially captured frames from the directory
    visualize_embeddings_2d(embeddings, samples_vis=False) # Visualize the embeddings first
    app.run(host="0.0.0.0", debug=True)
