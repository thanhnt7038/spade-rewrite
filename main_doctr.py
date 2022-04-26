import torch
import spade.models as models
import streamlit as st
import json
from google.cloud import vision
import os
from transformers import AutoConfig
import spade.transforms as transforms
import cProfile
from pprint import pformat
from detect.ocr import *
import spade.transforms as transforms
from spade.models import SpadeData
checkpoint_path="../best_score_parse.pt"
os.system("clear")
st.set_page_config(layout="wide")
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] =\
#     '/home/hung/grooo-gkeys.json'

st.header("Trích xuất hóa đơn")

config = Cfg.load_config_from_name('vgg_transformer')
config['weights'] = 'https://drive.google.com/uc?id=13327Y1tz1ohsm5YZMyXVMPIOjoOA0OaA'
config['cnn']['pretrained']=False
config['device'] = 'cuda:0'
config['predictor']['beamsearch']=False
detector_vietocr = Predictor(config)


@st.cache
def ocr(content: bytes):
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    return json.loads(type(response).to_json(response))

def ocr_doctr(image):
    model_doctr = detection_predictor(arch='db_resnet50', pretrained=True,assume_straight_pages=True)
    doct_img=DocumentFile.from_images(image)
    result=model_doctr(doct_img)
    img_copy=doct_img[0].copy()
    h,w,c=doct_img[0].shape
    bboxes=[]
    for box in result[0]:
        x1=int(box[0]*w)
        y1=int(box[1]*h)
        x2=int(box[2]*w)
        y2=int(box[3]*h)
        # bboxes.append([x1,x2,y1,y2])
        bboxes.insert(0,[x1,x2,y1,y2])
        img_copy=bounding_box(x1,y1,x2,y2,img_copy)
    st.image(img_copy, caption='Boxed_image')
    raw_text=Vietocr_img(img_copy,bboxes,detector_vietocr)
    return bboxes,raw_text,h,w

fields = [
    "store.name",
    "store.address",
    "store.phone",
    "menu.name",
    "menu.id",
    "menu.count",
    "menu.unit",
    "menu.unitprice",
    "menu.price",
    "menu.discount",
    "subtotal.tax",
    "subtotal.count",
    "subtotal.discount",
    "subtotal.service",
    "subtotal.price",
    "total.price",
    "total.currency",
    "total.cash",
    "total.credit",
    "total.change",
    "info.transaction",
    "info.customer",
    "info.time",
    "info.staff",
    "total.price_label",
    "total.cash_label",
    "total.change_label"]


@st.experimental_singleton
def get_model():
    config = AutoConfig.from_pretrained("vinai/phobert-base")
    model = models.BrosSpade(config, fields=fields)
    sd = torch.load(checkpoint_path, map_location='cpu')
    model.load_state_dict(sd, strict=False)
    return model


with st.spinner(text="Loading model"):
    model = get_model()
    st.success("Model loaded")

with st.spinner(text="Loading tokenizer"):
    tokenizer = st.experimental_singleton(models.AutoTokenizer)(
        "vinai/phobert-base", local_files_only=True)
    st.success("Tokenizer loaded")

upload_methods = ["Từ thư viện trong máy", "Chụp ảnh mới"]
upload_method = st.radio("Phương pháp upload ảnh", upload_methods)


if upload_methods.index(upload_method) == 0:
    image = st.file_uploader("Upload file")
else:
    image = st.camera_input("Chụp ảnh")

left, right = st.columns(2)
if image is not None:
    left.image(image)
    submit = left.button("Nhận dạng")
    clear = left.button("clear")
else:
    submit = clear = False

if submit:
    with st.spinner(text="OCR..."):
        bboxes,raw_text,h,w=ocr_doctr(image.getvalue())
        
        input_data=transforms.from_doctr(bboxes,raw_text,h,w)
    with st.spinner(text="Extracting features..."):
        import time
        a = time.time()
        batch = models.preprocess({
            "bbox_type": "xy4",
            "tokenizer": "vinai/phobert-base",
            "max_position_embeddings": 258
        }, input_data)
        b = time.time()
        print("Time", (b - a))

        for (k, v) in batch.items():
            print(k, v.shape)

    with st.spinner("Inferring..."):
        output = model(batch)

    with st.spinner("Post processing..."):
        final_output = models.post_process(
            tokenizer,
            relations=output.relations,
            batch=batch,
            fields=fields
        )
        right.code(json.dumps(final_output, ensure_ascii=False, indent=2))
