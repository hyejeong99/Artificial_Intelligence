import argparse
from operator import __ipow__
import cv2
from numpy.core.defchararray import array
from numpy.core.overrides import ARRAY_FUNCTION_ENABLED
from numpy.lib.polynomial import polyfit
import torch
from model import SCNN
from model_ENET_SAD import ENet_SAD
from utils.prob2lines import getLane
from utils.transforms import *
import time, random
from multiprocessing import Process, JoinableQueue, SimpleQueue
from threading import Lock
import matplotlib.pyplot as plt
img_size = (750, 320)#640, 360
#net = SCNN(input_size=(800, 288), pretrained=False)
net = ENet_SAD(img_size, sad=False)
# CULane mean, std
#mean=(0.3598, 0.3653, 0.3662)
#std=(0.2573, 0.2663, 0.2756)
mean=(0.15, 0.15, 0.15)
std=(0.22, 0.22, 0.22)
transform_img = Resize(img_size)
transform_to_net = Compose(ToTensor(), Normalize(mean=mean, std=std))
pipeline = False
i1_x = []
i1_y = []

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video_path", '-i', type=str, default="Ta2.mp4", help="Path to demo video")
    parser.add_argument("--weight_path", '-w', type=str, default="experiments/exp1/exp1_best.pth", help="Path to model weights")
    parser.add_argument("--visualize", '-v', action="store_true", default=True, help="Visualize the result")
    args = parser.parse_args()
    return args

def network(net, img):
    seg_pred, exist_pred = net(img.cuda())[:2]
    seg_pred = seg_pred.detach().cpu()
    exist_pred = exist_pred.detach().cpu()
    return seg_pred, exist_pred

def visualize(img, seg_pred, exist_pred):
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    img = cv2.add(img, (-50, -50, -50, 0))
    lane_img = np.zeros_like(img)
    color = np.array([[255, 125, 0], [0, 255, 0], [0, 0, 255], [0, 255, 255]], dtype='uint8')#b, g, r, y
    coord_mask = np.argmax(seg_pred, axis=0)
    exist = [1 if exist_pred[0, i] > 0.5 else 0 for i in range(4)]
    lines = []
    for i in getLane.prob2lines_CULane(seg_pred, exist):
        print(i)
        if len(i) < 8:
            continue
        i1_x = []
        i1_y = []
        for j in i:
            i1_x.append(j[0])
            i1_y.append(j[1])
        lines.append(np.polyfit(np.array(i1_x), np.array(i1_y), 2))

    yMax = img.shape[1]
    for li in range(len(lines)):
        #if exist_pred[0, li] > 0.5:
        #    lane_img[coord_mask == (li + 1)] = color[li]
        for Y in np.linspace(0, yMax-1, yMax):
            X = lines[li][0]*Y**2 + lines[li][1]*Y + lines[li][2]
            if(0 > Y) or (Y > 750):
                continue
            if (0 > X) or (X > 320):
                continue

            img[int(X), int(Y)]=color[li]

    #img = cv2.addWeighted(src1=lane_img, alpha=0.8, src2=img, beta=1., gamma=0.)
    return img
def pre_processor(arg):
    img_queue, video_path = arg
    cap = cv2.VideoCapture(video_path)
    while cap.isOpened():
        if img_queue.empty():
            ret, frame = cap.read()
            #plus
            height = frame.shape[0]
            width = frame.shape[1]
            if ret:
                frame = transform_img({'img': frame})['img']
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                x = transform_to_net({'img': img})['img']
                x.unsqueeze_(0)
                img_queue.put(x)
                img_queue.join()
            else:
                break
def post_processor(arg):
    img_queue, arg_visualize = arg
    while True:
        if not img_queue.empty():
            x, seg_pred, exist_pred = img_queue.get()
            seg_pred = seg_pred.numpy()[0]
            exist_pred = exist_pred.numpy()
            exist = [1 if exist_pred[0, i] > 0.5 else 0 for i in range(4)]
            if arg_visualize:
                frame = x.squeeze().permute(1, 2, 0).numpy()
                img = visualize(frame, seg_pred, exist_pred)
                cv2.imshow('input_video', frame)
                cv2.imshow("output_video", img)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            pass
def main():
    args = parse_args()
    video_path = args.video_path
    weight_path = args.weight_path
    if pipeline:
        input_queue = JoinableQueue()
        pre_process = Process(target=pre_processor, args=((input_queue, video_path),))
        pre_process.start()
        output_queue = SimpleQueue()
        post_process = Process(target=post_processor, args=((output_queue, args.visualize),))
        post_process.start()
    else:
        cap = cv2.VideoCapture(video_path)
    save_dict = torch.load(weight_path, map_location='cpu')
    net.load_state_dict(save_dict['net'])
    net.eval()
    net.cuda()
    while True:
        if pipeline:
            loop_start = time.time()
            x = input_queue.get()
            input_queue.task_done()
            gpu_start = time.time()
            seg_pred, exist_pred = network(net, x)
            gpu_end = time.time()
            output_queue.put((x, seg_pred, exist_pred))
            loop_end = time.time()
        else:
            if not cap.isOpened():
                break
            ret, frame = cap.read()
            if ret:
                loop_start = time.time()
                frame = transform_img({'img': frame})['img']
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                x = transform_to_net({'img': img})['img']
                x.unsqueeze_(0)
                gpu_start = time.time()
                seg_pred, exist_pred = network(net, x)
                gpu_end = time.time()
                seg_pred = seg_pred.numpy()[0]
                exist_pred = exist_pred.numpy()
                exist = [1 if exist_pred[0, i] > 0.5 else 0 for i in range(4)]
                i2i2 = []
                
                #change
                for i in getLane.prob2lines_CULane(seg_pred, exist):
                    i2i2 += i
                    pass
                loop_end = time.time()
                if args.visualize:
                    img = visualize(img, seg_pred, exist_pred)
                    cv2.imshow('input_video', frame)
                    cv2.imshow("output_video", img)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                break
        print("gpu_runtime:", gpu_end - gpu_start, "FPS:", int(1 / (gpu_end - gpu_start)))
        print("total_runtime:", loop_end - loop_start, "FPS:", int(1 / (loop_end - loop_start)))
    cv2.destroyAllWindows()
if __name__ == "__main__":
    main()