from __future__ import annotations
from typing import Any
from dataclasses import dataclass
import json
import time
import copy
import asyncio
import shutil
from pathlib import Path
import re
import math
import sys
import traceback
from enum import StrEnum
from base64 import b64encode
from io import BytesIO
import argparse

# Third party
import aiohttp
from PIL import Image, ImageFont, ImageDraw
import pyperclip

# Class to manipulate a vector2-type structure (X, Y)
# Call the 'i' property to obtain an integer tuple to use with Pillow
@dataclass(slots=True)
class V():
    x : int|float = 0
    y : int|float = 0
    
    def __init__(self : V, X : int|float, Y : int|float) -> None:
        self.x = X
        self.y = Y
    
    @staticmethod
    def ZERO() -> V:
        return V(0, 0)
    
    def copy(self : V) -> V:
        return V(self.x, self.y)
    
    # operators
    def __add__(self : V, other : V|tuple|list|int|float) -> V:
        if isinstance(other, float) or isinstance(other, int):
            return V(self.x + other, self.y + other)
        else:
            return V(self.x + other[0], self.y + other[1])
    
    def __radd__(self : V, other : V|tuple|list|int|float) -> V:
        return self.__add__(other)

    def __sub__(self : V, other : V|tuple|list|int|float) -> V:
        if isinstance(other, float) or isinstance(other, int):
            return V(self.x - other, self.y - other)
        else:
            return V(self.x - other[0], self.y - other[1])
    
    def __rsub__(self : V, other : V|tuple|list|int|float) -> V:
        return self.__sub__(other)

    def __mul__(self : V, other : V|tuple|list|int|float) -> V:
        if isinstance(other, float) or isinstance(other, int):
            return V(self.x * other, self.y * other)
        else:
            return V(self.x * other[0], self.y * other[1])

    def __rmul__(self : V, other : V|tuple|list|int|float) -> V:
        return self.__mul__(other)

    # for access via []
    def __getitem__(self : V, key : int) -> int|float:
        if key == 0:
            return self.x
        elif key == 1:
            return self.y
        else:
            raise IndexError("Index out of range")

    def __setitem__(self : V, key : int, value : int|float) -> None:
        if key == 0:
            self.x = value
        elif key == 1:
            self.y = value
        else:
            raise IndexError("Index out of range")

    # len is fixed at 2
    def __len__(self : V) -> int:
        return 2

    # to convert to an integer tuple (needed for pillow)
    @property
    def i(self : V) -> tuple[int, int]:
        return (int(self.x), int(self.y))

# Constants
IMAGE_SIZE : V = V(900, 1080)
THUMBNAIL_SIZE : V = V(1280, 720)
GBF_SIZE : V = V(640, 654)
CDN : str = "https://prd-game-a-granbluefantasy.akamaized.net/"

# Enums
class Language(StrEnum):
    undefined = ""
    english = "en"
    japanese = "ja"

# Utility functions
def read_clipboard() -> dict:
    return json.loads(pyperclip.paste())

def pexc(e : Exception) -> str:
    return "".join(traceback.format_exception(type(e), e, e.__traceback__))

"""
Handles 2D affine transformations using a 3x3 matrix representation.
The input 'data' is expected to be a flat list of 6 floats: [a, b, c, d, e, f]
representing the transformation:
| a  c  e |
| b  d  f |
| 0  0  1 |
"""
@dataclass(slots=True)
class Matrix3x3:
    data: list[float]

    @classmethod
    def from_state(cls, state):
        x, y = state[0], state[1]
        sx, sy = state[2], state[3]
        rot = math.radians(state[4]) if state[4] % 360 != 0 else 0
        # Note: ignore skewX and skewY
        rx, ry = state[7], state[8]
        
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        a, b = cos_r * sx, sin_r * sx
        c, d = -sin_r * sy, cos_r * sy
        tx = x - (rx * a + ry * c)
        ty = y - (rx * b + ry * d)
        return cls([a, b, c, d, tx, ty])

    def multiply(self, other: Matrix3x3) -> Matrix3x3:
        m1 = [[self.data[0], self.data[2], self.data[4]],
              [self.data[1], self.data[3], self.data[5]], [0, 0, 1]]
        m2 = [[other.data[0], other.data[2], other.data[4]],
              [other.data[1], other.data[3], other.data[5]], [0, 0, 1]]
        res = [[0.0]*3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    res[i][j] += m1[i][k] * m2[k][j]
        return Matrix3x3([res[0][0], res[1][0], res[0][1], res[1][1], res[0][2], res[1][2]])

    def get_pillow_affine(self) -> list[float]:
        # inverts the matrix for Pillow's .transform() method
        m = [[self.data[0], self.data[2], self.data[4]],
             [self.data[1], self.data[3], self.data[5]], [0.0, 0.0, 1.0]]
        try:
            inv = self.invert_matrix(m)
        except ValueError:
            # to avoid crash
            return [1.0, 0, 0, 0, 1.0, 0]
        # Pillow wants: (a, b, c, d, e, f) where x_src = ax_dst + by_dst + c
        return [inv[0][0], inv[0][1], inv[0][2], inv[1][0], inv[1][1], inv[1][2]]

    @staticmethod
    def invert_matrix(matrix: list[list[float]]) -> list[list[float]]:
        # inverts a square matrix using Gauss-Jordan elimination.
        n = len(matrix)
        # create an identity matrix of the same size
        inverse = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        # work on a copy to avoid mutating the original
        working_matrix = copy.deepcopy(matrix)
        
        for i in range(n):
            # pivot scaling: make the diagonal element 1.0
            pivot = working_matrix[i][i]
            if abs(pivot) < 1e-9:
                raise ValueError("Matrix is singular and cannot be inverted.")
            scaling_factor = 1.0 / pivot
            for j in range(n):
                working_matrix[i][j] *= scaling_factor
                inverse[i][j] *= scaling_factor
            # make all other elements in this column 0.0
            for k in range(n):
                if k != i:
                    factor = working_matrix[k][i]
                    for j in range(n):
                        working_matrix[k][j] -= factor * working_matrix[i][j]
                        inverse[k][j] -= factor * inverse[i][j]
        return inverse

# Wrapper class to store and manipulate Image objects
# Handle the close() calls on destruction
@dataclass(slots=True)
class IMG():
    image : Image = None
    buffer : BytesIO = None
    
    def __init__(self : IMG, src : str|bytes|IMG|Image, *, auto_convert : bool = True) -> None:
        self.image = None
        self.buffer = None
        match src: # possible types
            case str(): # path to a local file
                self.image = Image.open(src)
                if auto_convert:
                    self.convert("RGBA")
            case bytes(): # bytes (usually received from a network request)
                self.buffer = BytesIO(src) # need a readable buffer for it, and it must stays alive
                self.image = Image.open(self.buffer)
                if auto_convert:
                    self.convert("RGBA")
            case IMG(): # another IMG wrapper
                self.image = src.image.copy()
            case _: # an Image instance. NOTE: I use 'case _' because of how import Pillow, the type isn't loaded at this point
                self.image = src

    @staticmethod
    def new_canvas(size : V|None = None) -> IMG:
        if size is None:
            size = IMAGE_SIZE
        i : Image = Image.new('RGB', size.i, "black")
        im_a : Image = Image.new("L", size.i, "black") # Alpha
        i.putalpha(im_a)
        im_a.close()
        return IMG(i)

    def __del__(self : IMG) -> None:
        if self.image is not None:
            self.image.close()
        if self.buffer is not None:
            self.buffer.close()

    def swap(self : IMG, other : IMG) -> None:
        self.image, other.image = other.image, self.image
        self.buffer, other.buffer = other.buffer, self.buffer

    def convert(self : IMG, itype : str) -> None:
        tmp = self.image
        self.image = tmp.convert(itype)
        tmp.close()

    def copy(self : IMG) -> IMG:
        return IMG(self)

    def paste(self : IMG, other : IMG, offset : V|tuple[int, int]) -> None:
        match offset:
            case V():
                self.image.paste(other.image, offset.i, other.image)
            case _:
                self.image.paste(other.image, offset, other.image)

    def paste_transparency(self : IMG, other : IMG, offset : V|tuple[int, int]) -> None:
        alpha : IMG = IMG.new_canvas(V(self.image.size[0], self.image.size[1]))
        alpha.paste(other, offset)
        self.swap(self.alpha(alpha))

    def crop(self : IMG, size : tuple[int, int]|tuple[int, int, int, int]) -> IMG:
        # depending on the tuple size
        if len(size) == 4:
            return IMG(self.image.crop(size))
        elif len(size) == 2:
            return IMG(self.image.crop((0, 0, *size)))
        raise ValueError(f"Invalid size of the tuple passed to IMG.crop(). Expected 2 or 4, received {len(size)}.")

    def resize(self : IMG, size : V|tuple[int, int]) -> IMG:
        match size:
            case V():
                return IMG(self.image.resize(size.i, Image.Resampling.LANCZOS))
            case tuple():
                return IMG(self.image.resize(size, Image.Resampling.LANCZOS))
        raise TypeError(f"Invalid type passed to IMG.resize(). Expected V or tuple[int, int], received {type(size)}.")

    def rotate(self : IMG, angle : int, center : V|tuple[int, int]|None = None) -> IMG:
        match center:
            case V():
                return IMG(self.image.rotate(angle, center=center.i, resample=Image.BICUBIC))
            case tuple():
                return IMG(self.image.rotate(angle, center=center, resample=Image.BICUBIC))
            case None:
                return IMG(self.image.rotate(angle, resample=Image.BICUBIC))
        raise TypeError(f"Invalid type passed to IMG.rotate(). Expected V or tuple[int, int], received {type(center)}.")

    def thumbnail(self : IMG, size : V|tuple[int, int]) -> IMG:
        match size:
            case V():
                return IMG(self.image.thumbnail(size.i, Image.Resampling.LANCZOS))
            case tuple():
                return IMG(self.image.thumbnail(size, Image.Resampling.LANCZOS))
        raise TypeError(f"Invalid type passed to IMG.thumbnail(). Expected V or tuple[int, int], received {type(size)}.")

    def ninepatch(self : IMG, size : V|tuple[int, int], margin : int) -> IMG:
        iw, ih = self.image.size
        match size:
            case V():
                tw, th = size.i
            case tuple():
                tw, th = size
            case _:
                raise TypeError(f"Invalid type passed to IMG.ninepatch(). Expected V or tuple[int, int], received {type(size)}.")

        # output image
        out : IMG = IMG(Image.new("RGBA", (tw, th)))
        # corners
        out.paste(self.crop((0, 0, margin, margin)), (0, 0)) # TL
        out.paste(self.crop((iw - margin, 0, iw, margin)), (tw - margin, 0)) # TR
        out.paste(self.crop((0, ih - margin, margin, ih)), (0, th - margin)) # BL
        out.paste(self.crop((iw - margin, ih - margin, iw, ih)), (tw - margin, th - margin)) # BR
        # edges
        out.paste(self.crop((margin, 0, iw - margin, margin)).resize((tw - margin - margin, margin)), (margin, 0)) # margin
        out.paste(self.crop((margin, ih - margin, iw - margin, ih)).resize((tw - margin - margin, margin)), (margin, th - margin)) # margin
        out.paste(self.crop((0, margin, margin, ih - margin)).resize((margin, th - margin - margin)), (0, margin)) # margin
        out.paste(self.crop((iw - margin, margin, iw, ih - margin)).resize((margin, th - margin - margin)), (tw - margin, margin)) # margin
        # center
        center_w = tw - margin - margin
        center_h = th - margin - margin
        if center_w > 0 and center_h > 0:
            out.paste(self.crop((margin, margin, iw - margin, ih - margin)).resize((center_w, center_h)), (margin, margin))
        return out

    def transpose(self : IMG, i : int) -> None:
        tmp = self.image.transpose(i)
        self.image.close()
        self.image = tmp

    def transform(self : IMG, m : Matrix3x3) -> IMG:
        return IMG(
            self.image.transform(
                self.image.size,
                Image.Transform.AFFINE,
                m.get_pillow_affine(),
                resample=Image.Resampling.BILINEAR
            )
        )

    def text(self : IMG, *args, **kwargs) -> IMG:
        ImageDraw.Draw(self.image, 'RGBA').text(*args, **kwargs)
        return self

    def alpha(self : IMG, layer : IMG) -> IMG:
        return IMG(Image.alpha_composite(self.image, layer.image))

    def show(self : IMG) -> None:
        self.image.show()

    def save(self : IMG, path : str, dry : bool = False) -> None:
        if not dry:
            self.image.save(path, "PNG")

# Classes to parse CreateJS raid_appear animations and generate an image
@dataclass
class TweenStep:
    type: str # 'to' or 'wait'
    props: dict
    duration: int

@dataclass
class Instance:
    name: str
    symbol_name: str
    transform: list[float] # x, y, scaleX, scaleY, rotation, skewX, skewY, regX, regY
    tweens: list[TweenStep]
    initial_props: dict = None

@dataclass
class Symbol:
    name: str
    type: str # 'Bitmap' or 'MovieClip'
    source_rect: list[int] = None # For Bitmaps: x, y, w, h
    instances: list[Instance] = None # For MovieClips
    total_frames: int = 1
    stop_frame: int | None = None

class CreateJSTimelineParser:
    def __init__(self : CreateJSTimelineParser, name : str, js_data : str, atlas : IMG) -> None:
        self.name = name
        self.js_data = js_data
        self.atlas = atlas
        self.symbols: dict[str, Symbol] = {}
        self._parse()

    def _parse(self : CreateJSTimelineParser) -> None:
        # parse sub-rectangles, i.e. bitmaps
        bitmap_re = re.compile(r"\(a\.(\w+)=function\(\)\{this\.sourceRect=new c\.Rectangle\((\d+),(\d+),(\d+),(\d+)\),this\.initialize\(b\.\w+\)\}\)\.prototype=(?:[a-z]|lib)=new c\.Bitmap")
        for match in bitmap_re.finditer(self.js_data):
            name, x, y, w, h = match.groups()
            self.symbols[name] = Symbol(name=name, type="Bitmap", source_rect=[int(x), int(y), int(w), int(h)])

        # parse MovieClips
        mc_re = re.compile(r"\(a\.(\w+)=function\(.*?\)\{(.*?)\}\)\.prototype=(?:(?:[a-z]|lib)=new c\.(?:MovieClip|Container)|d\(a\.\1,.*?\)|(?:[a-z]|lib)=new c\.Bitmap)")
        for match in mc_re.finditer(self.js_data):
            name, body = match.groups()
            if name not in self.symbols:
                # don't overwrite bitmap if already parsed
                self.symbols[name] = self._parse_movieclip(name, body)

    def _parse_movieclip(self : CreateJSTimelineParser, name : str, body : str) -> Symbol:
        # use a list to preserve Z-index
        instances: list[Instance] = []
        inst_map: dict[str, Instance] = {}

        # search stop frame
        stop_frame = None
        stop_match = re.search(r"this\.frame_(\d+)\s*=\s*function\s*\(\)\s*\{\s*this\.stop\(\)\s*\}", body)
        if stop_match:
            stop_frame = int(stop_match.group(1))
            
        # parse instances and their symbols
        # Example: this.instance=new a.raid_appear_9102383_vs_b
        inst_re = re.compile(r"this\.(\w+)=new a\.(\w+)")
        for inst_match in inst_re.finditer(body):
            inst_name, sym_name = inst_match.groups()
            if not sym_name:
                sym_name = inst_name 
            inst = Instance(
                name=inst_name,
                symbol_name=sym_name,
                transform=[0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                tweens=[],
                initial_props={}
            )
            instances.append(inst)
            inst_map[inst_name] = inst

        # parse initial property assignments
        # Example: this.instance.alpha=.1289; this.instance._off=!0;
        prop_re = re.compile(r"this\.(\w+)\.(\w+)=([^,;]+)")
        for prop_match in prop_re.finditer(body):
            inst_name, prop, val = prop_match.groups()
            if inst_name in inst_map and prop not in ("setTransform", "timeline"):
                val = val.strip()
                if val == "!0":
                    val = True
                elif val == "!1":
                    val = False
                else:
                    try:
                        val = float(val)
                    except ValueError:
                        # strip quotes from strings
                        val = val.strip("'\"")
                inst_map[inst_name].initial_props[prop] = val

        # parse setTransform
        # Example: this.instance.setTransform(162,134,1,1,0,0,0,12,4)
        trans_re = re.compile(r"this\.(\w+)\.setTransform\((.*?)\)")
        for trans_match in trans_re.finditer(body):
            inst_name, params_str = trans_match.groups()
            if inst_name in inst_map:
                params = []
                for p in params_str.split(","):
                    try:
                        params.append(float(p))
                    except ValueError:
                        params.append(0.0)
                # CreateJS setTransform: x, y, scaleX, scaleY, rotation, skewX, skewY, regX, regY
                # pad to 9
                full_params = params + [0.0] * (9 - len(params))
                # default scaleX/scaleY to 1.0 if not provided
                if len(params) < 3:
                    full_params[2] = 1.0
                if len(params) < 4:
                    full_params[3] = 1.0
                inst_map[inst_name].transform = full_params

        # parse Tweens
        # Example: this.timeline.addTween(c.Tween.get(this.instance_7).wait(10).to({_off:!1},0)...)
        tween_re = re.compile(r"this\.timeline\.addTween\(c\.Tween\.get\(this(?:\.(\w+))?\)(.*?)\)(?=[,;}])")
        max_duration = 1
        for tween_match in tween_re.finditer(body):
            inst_name, actions_str = tween_match.groups()
            if inst_name is None:
                inst_name = "this"
            
            tweens = []
            current_duration = 0
            
            # parse .to({props}, duration) and .wait(duration)
            action_re = re.compile(r"\.(to|wait)\((.*?)\)")
            for action_match in action_re.finditer(actions_str):
                atype, params = action_match.groups()
                if atype == "to":
                    prop_match = re.search(r"\{(.*?)\}", params)
                    props = {}
                    if prop_match:
                        prop_str = prop_match.group(1)
                        for p in prop_str.split(","):
                            if ":" in p:
                                k, v = p.split(":", 1)
                                k, v = k.strip(), v.strip()
                                if v == "!0":
                                    v = True
                                elif v == "!1":
                                    v = False
                                else:
                                    try: v = float(v)
                                    except:
                                        v = v.strip("'\"")
                                props[k] = v
                    # duration is the number after the properties block
                    dur_match = re.search(r"\},(\d+)", params)
                    duration = int(dur_match.group(1)) if dur_match else 0
                    tweens.append(TweenStep(type="to", props=props, duration=duration))
                    current_duration += duration
                else:
                    # wait(10) or wait(1).call(...)
                    dur_match = re.match(r"^(\d+)", params)
                    duration = int(dur_match.group(1)) if dur_match else 0
                    tweens.append(TweenStep(type="wait", props={}, duration=duration))
                    current_duration += duration
            
            if inst_name != "this" and inst_name in inst_map:
                inst_map[inst_name].tweens = tweens
            
            max_duration = max(max_duration, current_duration)

        return Symbol(name=name, type="MovieClip", instances=instances, total_frames=max_duration, stop_frame=stop_frame)

    def _get_instance_state(self : CreateJSTimelineParser, instance : Instance, frame : int) -> dict:
        # calculates the state of an instance at a specific frame
        state : dict = { # initial state
            'x': instance.transform[0],
            'y': instance.transform[1],
            'scaleX': instance.transform[2],
            'scaleY': instance.transform[3],
            'rotation': instance.transform[4],
            'skewX': instance.transform[5],
            'skewY': instance.transform[6],
            'regX': instance.transform[7],
            'regY': instance.transform[8],
            'alpha': 1.0,
            '_off': False
        }
        
        # override with initial properties
        if instance.initial_props:
            state.update(instance.initial_props)

        if not instance.tweens:
            return state

        elapsed : int = 0
        for i, step in enumerate(instance.tweens):
            if frame < elapsed:
                break
                
            if step.type == "wait":
                elapsed += step.duration
                if frame < elapsed:
                    # during wait, state remains
                    break
            elif step.type == "to":
                start_frame = elapsed
                end_frame = elapsed + step.duration
                
                if frame >= end_frame:
                    # step is finished, apply all properties
                    state.update(step.props)
                    elapsed = end_frame
                else:
                    # interpolate
                    t = (frame - start_frame) / step.duration if step.duration > 0 else 1.0
                    for prop, end_val in step.props.items():
                        if prop in state:
                            if isinstance(end_val, (int, float)) and isinstance(state[prop], (int, float)):
                                state[prop] = state[prop] + (end_val - state[prop]) * t
                            else:
                                state[prop] = end_val
                        else:
                            state[prop] = end_val
                    elapsed = end_frame
                    break
        return state

    def render(self : CreateJSTimelineParser, target_frame: int = -1) -> IMG:
        # priority for target symbol: mc_{name}_set, then mc_{name}, then {name}
        # latter two are untested, they're here for fallback purpose
        target_name = None
        candidates = [f"mc_{self.name}_set", f"mc_{self.name}", self.name]
        for candidate in candidates:
            if candidate in self.symbols:
                target_name = candidate
                break
        
        # fallback: find any symbol that ends with _set and contains the ID
        if not target_name:
            boss_id = self.name.split('_')[-1]
            for sym_name in self.symbols:
                if sym_name.endswith('_set') and boss_id in sym_name:
                    target_name = sym_name
                    break
        
        if not target_name:
            # keep this print for debug
            print(f"Warning: Could not find target symbol for {self.name}. Available symbols: {list(self.symbols.keys())[:5]}...")
            return None

        symbol = self.symbols[target_name]

        if target_frame == -1:
            # Start with finding the frame with the maximum number of visible bitmaps
            max_visible = -1
            best_frames = []
            
            # Search all frames in the target symbol
            bitmaps_per_frame = []
            for f in range(symbol.total_frames):
                visible_count = self._count_visible_bitmaps(symbol, f)
                if visible_count > max_visible:
                    max_visible = visible_count
                    best_frames = [f]
                elif visible_count == max_visible:
                    best_frames.append(f)
                bitmaps_per_frame.append(visible_count)
            
            if best_frames:
                # prefer frames that are also stop frames
                stop_frames_in_best = [f for f in best_frames if f == symbol.stop_frame]
                if stop_frames_in_best:
                    target_frame = stop_frames_in_best[0]
                else:
                    # else try to ballpark from the list of bitmap count per frame
                    highest = max(bitmaps_per_frame)
                    start = bitmaps_per_frame.index(highest)
                    for i in range(start, len(bitmaps_per_frame)):
                        if bitmaps_per_frame[i] < highest:
                            target_frame = i + 1 # pick next one after
                            start = None
                            break
                    if start is not None:
                        # fallback
                        target_frame = symbol.total_frames - 1
            else:
                target_frame = symbol.total_frames - 1

        # output canvas
        canvas = IMG.new_canvas(GBF_SIZE) # gbf resolution
        self._render_recursive(canvas, symbol, target_frame, Matrix3x3([1.0, 0, 0, 1.0, 0, 0]), 1.0)
        return canvas

    def _render_recursive(
        self : CreateJSTimelineParser,
        canvas : IMG, symbol : Symbol,
        frame : int, parent_matrix : Matrix3x3,
        parent_alpha : float, composite : str = None
    ) -> None:
        if symbol.type == "Bitmap":
            rect = symbol.source_rect
            cropped : IMG = self.atlas.crop((rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]))
            
            temp : IMG = IMG.new_canvas(GBF_SIZE)
            temp.paste(cropped, (0, 0))
            
            # apply alpha
            if parent_alpha < 1.0:
                r, g, b, a = temp.image.split()
                a = a.point(lambda p: int(p * parent_alpha))
                temp.image.putalpha(a)
            
            transformed : IMG = temp.transform(parent_matrix)
            # Note: I ignore direct "lighter" composite and additive blending
            canvas.swap(canvas.alpha(transformed))
        elif symbol.type == "MovieClip":
            # renders instances in the order they were added to the timeline,
            # which usually corresponds to the order in the code.
            for instance in reversed(symbol.instances):
                state = self._get_instance_state(instance, frame)
                if state.get('_off', False):
                    continue
                alpha = state.get('alpha', 1.0) * parent_alpha
                if alpha <= 0:
                    continue
                inst_state_list = [
                    state['x'], state['y'],
                    state['scaleX'], state['scaleY'],
                    state['rotation'],
                    state['skewX'], state['skewY'],
                    state['regX'], state['regY']
                ]
                inst_matrix = Matrix3x3.from_state(inst_state_list)
                combined_matrix = parent_matrix.multiply(inst_matrix)
                child_symbol = self.symbols[instance.symbol_name]
                child_frame = frame % child_symbol.total_frames
                # pass down compositeOperation if set on instance
                child_composite = state.get('compositeOperation', composite)
                self._render_recursive(canvas, child_symbol, child_frame, combined_matrix, alpha, child_composite)

    def _count_visible_bitmaps(self : CreateJSTimelineParser, symbol : Symbol, frame : int, alpha_threshold : float = 0.1) -> int:
        # recursively counts the number of visible Bitmaps at a specific frame
        if symbol.type == "Bitmap":
            return 1
        count = 0
        if symbol.type == "MovieClip":
            for instance in symbol.instances:
                state = self._get_instance_state(instance, frame)
                if state.get('_off', False) or state.get('alpha', 1.0) < alpha_threshold:
                    continue
                child_symbol = self.symbols[instance.symbol_name]
                child_frame = frame % child_symbol.total_frames
                count += self._count_visible_bitmaps(child_symbol, child_frame, alpha_threshold)
        return count

# Layout of the party images
@dataclass(slots=True)
class LayoutPartyBase():
    origin : V
    bg_size : V
    bg_margin : V
    box_margin : int
    party_groups : list[tuple[V, int, str|None]]
    group_text_offset : V
    job_icon_size : V
    star_icon_size : V
    arousal_icon_size : V
    portrait_icon_offset : V
    portrait_size : V
    plus_offset : V
    ring_size : V
    ring_offset : V
    name_box_size : V
    name_offset : V
    show_name : bool
    name_character_limit : int
    skill_offset : V
    skill_size : V
    skill_text_offset : V
    skill_text_line_height : int
    equipment_size : V
    equipment_offset : V

    def __init__(self : LayoutPartyBase) -> None:
        self.origin = V.ZERO()
        self.bg_size = V(IMAGE_SIZE.x, 300)
        self.bg_margin = 5
        self.party_groups = []
        self.name_box_size = V.ZERO()
        self.name_offset = V.ZERO()
        self.show_name = False
        self.name_character_limit = 9

    def groups(self : LayoutPartyBase, len_party : int):
        index : int = 0
        position : V = self.party_groups[index][0]
        left : int = self.party_groups[index][1]
        for i in range(len_party):
            if left == self.party_groups[index][1]:
                yield (
                    i,
                    position,
                    self.party_groups[index][2]
                )
            else:
                yield (
                    i,
                    position,
                    ""
                )
            left -= 1
            position += V(self.portrait_size.x, 0)
            if left == 0 and index < len(self.party_groups) - 1:
                index += 1
                position = self.party_groups[index][0]
                left = self.party_groups[index][1]
            
class LayoutPartyNormal(LayoutPartyBase):
    def __init__(self : LayoutPartyNormal) -> None:
        super().__init__()
        self.box_margin = 5
        self.party_groups = [
            (self.origin + V(18, 25), 4, "text_main"),
            (self.origin + V(18 * 2 + 140 * 4, 25), 2, "text_sub"),
        ]
        self.group_text_offset = V(-15, -20)
        self.job_icon_size = V(48, 40)
        self.star_icon_size = V(40, 40)
        self.arousal_icon_size = V(60, 60)
        self.portrait_icon_offset = V(1, 1)
        self.portrait_size = V(140, 140)
        self.plus_offset = V(10, self.portrait_size.y - 35)
        self.ring_size = V(60, 60)
        self.ring_offset = V(self.portrait_size.x - self.ring_size.x, 0)
        self.name_box_size = V(self.portrait_size.x, 40)
        self.name_offset = V(5, 10)
        self.show_name = True
        self.skill_offset = self.party_groups[0][0] + V(0, self.portrait_size.y + self.name_box_size.y + 10)
        self.skill_size = V(539, 80)
        self.skill_text_offset = V(5, 4)
        self.skill_text_line_height = 27
        self.equipment_size = V(80, 80)
        self.equipment_offset = self.skill_offset + V(self.skill_size.x + 20, 0)
    
class LayoutPartyUnlimited(LayoutPartyNormal):
    def __init__(self : LayoutPartyUnlimited) -> None:
        super().__init__()
        self.party_groups = [
            (self.origin + V(18, 25), 4, "text_main"),
            (self.origin + V(18, 25 + 140), 5, "text_sub"),
        ]
        self.portrait_size = V(120, 120)
        self.star_icon_size = V(40, 40)
        self.arousal_icon_size = V(50, 50)
        self.plus_offset = V(10, self.portrait_size.y - 35)
        self.show_name = False
        self.ring_size = V(50, 50)
        self.ring_offset = V(self.portrait_size.x - self.ring_size.x, 0)
        self.skill_offset = self.party_groups[0][0] + V(self.portrait_size.x * 4 + 5 , 0)
        self.skill_size = V(380, 80)
        self.equipment_offset = self.party_groups[1][0] + V(self.portrait_size.x * 5 + 20 , 0)
        self.equipment_size = V(120, 120)
    
class LayoutPartyBabyl(LayoutPartyUnlimited):
    def __init__(self : LayoutPartyBabyl) -> None:
        super().__init__()
        self.party_groups = [
            (self.origin + V(18, 25), 4, ""),
            (self.origin + V(18 * 2 + 100 * 4, 25), 4, ""),
            (self.origin + V(18, 25 + 100 + 30), 4, "text_sub"),
        ]
        self.portrait_size = V(100, 100)
        self.star_icon_size = V(40, 40)
        self.arousal_icon_size = V(40, 40)
        self.plus_offset = V(10, self.portrait_size.y - 35)
        self.show_name = False
        self.ring_size = V(40, 40)
        self.ring_offset = V(self.portrait_size.x - self.ring_size.x, 0)
        self.skill_offset = self.party_groups[1][0] + V(0, self.portrait_size.y + 30)
        self.skill_size = V(330, 80)
        self.equipment_offset = self.skill_offset + V(self.skill_size.x + 10 , 0)
        self.equipment_size = V(100, 100)

@dataclass(slots=True)
class LayoutSummon():
    origin : V
    bg_size : V
    bg_margin : int
    main_position : V
    main_size : V
    sub_position : V
    sub_size : V
    sub_offset : V
    extra_position : V
    extra_size : V
    extra_offset : V
    plus_offset : V
    quick_offset : V
    quick_size : V
    support_position : V
    support_size : V

    def __init__(self : LayoutSummon) -> None:
        self.origin = V(0, 300)
        self.bg_size = V(IMAGE_SIZE.x, 200)
        self.bg_margin = 5
        self.main_position = self.origin + V(12, 10)
        self.main_size = V(180, 180)
        self.sub_position = self.main_position + V(self.main_size.x + 15, 0)
        self.sub_size = V(157, 90)
        self.sub_offset = self.sub_size
        self.extra_position = self.sub_position + V(self.sub_size.x * 2 + 15, 0)
        self.extra_size = self.sub_size
        self.extra_offset = self.sub_size
        self.plus_offset = V(-70, - 35)
        self.quick_offset = V(5, 5)
        self.quick_size = V(50, 50)
        self.support_position = self.extra_position + V(self.extra_size.x + 15, 0)
        self.support_size = self.main_size

@dataclass(slots=True)
class LayoutWeapon():
    max_weapon : int
    box_margin : int
    origin : V
    bg_size : V
    main_position : V
    main_size : V
    sub_position : V
    sub_size : V
    sub_offset : V
    skill_size : V
    skill_spacer : int
    skill_text_offset : V
    plus_offset : V
    awakening_size : V

    def __init__(self : LayoutWeapon) -> None:
        self.max_weapon = 10
        self.box_margin = 5
        self.bg_size = V(IMAGE_SIZE.x - 150, 570)
        self.origin = V((IMAGE_SIZE.x - self.bg_size.x) // 2, 500)
        self.main_position = self.origin + V(15, 20) + V(0, 70)
        self.main_size = V(150, 320)
        self.sub_position = self.main_position - V(0, 70) + V(self.main_size.x + 15, 0)
        self.sub_size = V(166, 95)
        self.skill_size = V(40, 40)
        self.skill_spacer = self.sub_size.x // 2 - self.skill_size.x
        self.skill_text_offset = V(0, 6)
        self.sub_offset = self.sub_size + V(10, self.skill_size.y * 2)
        self.plus_offset = V(-60, -40)
        self.awakening_size = V(50, 50)

class LayoutWeaponExtra(LayoutWeapon):
    def __init__(self : LayoutWeaponExtra) -> None:
        super().__init__()
        self.max_weapon = 13
        self.bg_size = V(IMAGE_SIZE.x, 570)
        self.origin = V(0, 500)
        self.main_position = self.origin + V(15, 20) + V(0, 70)
        self.sub_position = self.main_position - V(0, 70) + V(self.main_size.x + 15, 0)

@dataclass(slots=True)
class LayoutEstimate():
    origin : V
    bg_size : V
    bg_margin : int
    stat_size : V
    stat_offset : V
    stat_text_icon_offset : V
    stat_text_offset : V
    estimate_size : V
    estimate_offset : tuple[V, V]
    estimate_text_offset : V
    estimate_sub_text_offset : V
    vs_offset : V
    hp_bar_size : V
    hp_bar_offset : V
    boost_origin : V
    boost_size : V
    boost_text_offset : V
    boost_horizontal_offset : int

    def __init__(self : LayoutEstimate) -> None:
        self.origin = V(0, 300)
        self.bg_size = V(IMAGE_SIZE.x, 180)
        self.bg_margin = 5
        self.stat_size = V(300, 50)
        self.stat_offset = self.origin + V(10, 5)
        self.stat_text_icon_offset = V(20, 10)
        self.stat_text_offset = V(100, 5)
        self.estimate_size = V(250, 110)
        self.estimate_offset = (
            self.stat_offset + V(self.stat_size.x + 20, 0),
            self.stat_offset + V(self.stat_size.x + self.estimate_size.x + 30, 0)
        )
        self.estimate_text_offset = V(25, 15)
        self.estimate_sub_text_offset = self.estimate_text_offset + V(0, 35 + self.estimate_text_offset.y)
        self.vs_offset = V(40, 0)
        self.hp_bar_size = V(300, 20)
        self.hp_bar_offset = self.stat_offset + V(0, self.stat_size.y * 2 + 10)
        self.boost_origin = self.estimate_offset[0] + V(0, self.estimate_size.y + 5)
        self.boost_size = V(50, 50)
        self.boost_text_offset = V(self.boost_size.x + 10, 10)
        self.boost_horizontal_offset = 160

@dataclass(slots=True)
class LayoutModifier():
    origin : V
    bg_size : V
    bg_margin : int
    mod_offset_start : V
    mod_size : V
    mod_box : V
    mod_per_line : int
    mod_horizontal_offset : int
    mod_vertical_offset : int
    mod_text_offset : V

    def __init__(self : LayoutEstimate) -> None:
        self.origin = V(0, 480)
        self.bg_margin = 5
        self.mod_offset_start = self.origin + V(5, 10)
        self.mod_size = V(132, 34)
        self.mod_box = V(145, 35)
        self.mod_per_line = 6
        self.mod_horizontal_offset = 148
        self.mod_vertical_offset = 70
        self.mod_text_offset = V(5, 5 + self.mod_vertical_offset / 2)

@dataclass(slots=True)
class LayoutEMP():
    origin : V
    size : V
    margin : int
    offset : V
    portrait_size : V
    portrait_folder : str
    portrait_offset : V
    emp_start_offset : V
    emp_size : tuple[V, V]
    emp_per_line : tuple[int, int]
    emp_count_offset : V
    emp_count_font : int
    arousal_icon_size : V
    arousal_icon_offset : V
    ring_size : V
    ring_offset : V
    extra_compact_mode : int
    extra_icon_size : V
    extra_start_offset : V
    extra_per_line : int
    extra_line_jump : int
    extra_text_offset : V
    extra_offset : V
    domain_offset : V
    domain_size : V
    domain_text_offset : V

    def __init__(self : LayoutEMP) -> None:
        self.origin = V(0, 0)
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 5)
        self.margin = 5
        self.offset = V(0, self.size.y)
        self.portrait_size = V(196, 408) * (self.size.y  / 408.0)
        self.portrait_folder = "f"
        self.portrait_offset = V(2, 0)
        self.emp_start_offset = V(self.offset.x + self.portrait_size.x + 2, 0)
        self.emp_size = (
            V(self.portrait_size.y // 3, self.portrait_size.y // 3),
            V(self.portrait_size.y // 4, self.portrait_size.y // 4),
        )
        self.emp_per_line = (
            5,
            5
        )
        self.emp_count_offset = V(10, 5)
        self.emp_count_font = 3
        self.arousal_icon_size = V(60, 60)
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_size = V(60, 60)
        self.ring_offset = self.portrait_offset
        self.extra_compact_mode = 0
        self.extra_icon_size = V(40, 40)
        self.extra_start_offset = self.emp_start_offset + V(self.emp_size[0].y * 5 + 20, 5)
        self.extra_per_line = 1000
        self.extra_text_offset = V(45, 10)
        self.extra_offset = V(0, 40)
        self.domain_offset = V(0, 0)
        self.domain_offset = self.extra_start_offset + V(250, 0)
        self.domain_size = V(40, 40)
        self.domain_text_offset = V(self.domain_size.x + 10, 10)

class LayoutEMPCompact(LayoutEMP):
    def __init__(self : LayoutEMPCompact) -> None:
        super().__init__()
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 8)
        self.offset = V(0, self.size.y)
        self.portrait_size = V(self.size.y, self.size.y)
        self.portrait_folder = "s"
        self.emp_start_offset = V(self.offset.x + self.portrait_size.x + 2, 0)
        self.emp_size = (
            V((IMAGE_SIZE.x - self.portrait_size.x - self.portrait_offset.x) // 15, 0),
            V((IMAGE_SIZE.x - self.portrait_size.x - self.portrait_offset.x) // 20, 0),
        )
        self.emp_size[0].y = self.emp_size[0].x
        self.emp_size[1].y = self.emp_size[1].x
        self.emp_per_line = (
            1000,
            1000
        )
        self.emp_count_font = 2
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_offset = self.portrait_offset
        self.extra_compact_mode = 1
        self.extra_icon_size = V(40, 40)
        self.extra_start_offset = self.emp_start_offset + V(5, 45)
        self.extra_per_line = 3
        self.extra_line_jump = 40
        self.extra_text_offset = V(45, 10)
        self.extra_offset = V(250, 0)
        self.domain_offset = self.extra_start_offset + self.extra_offset * 2 + V(0, self.extra_line_jump)
        self.domain_size = V(40, 40)
        self.domain_text_offset = V(self.domain_size.x + 10, 10)

class LayoutEMPVeryCompact(LayoutEMPCompact):
    def __init__(self : LayoutEMPVeryCompact) -> None:
        super().__init__()
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 11)
        self.offset = V(0, self.size.y)
        self.portrait_size = V(self.size.y, self.size.y)
        self.portrait_folder = "s"
        self.emp_start_offset = V(self.offset.x + self.portrait_size.x + 2, 0)
        self.emp_size = (
            V((IMAGE_SIZE.x - self.portrait_size.x - self.portrait_offset.x) // 15, 0),
            V((IMAGE_SIZE.x - self.portrait_size.x - self.portrait_offset.x) // 20, 0),
        )
        self.emp_size[0].y = self.emp_size[0].x
        self.emp_size[1].y = self.emp_size[1].x
        self.emp_per_line = (
            1000,
            1000
        )
        self.emp_count_font = 1
        self.arousal_icon_size = V(40, 40)
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_size = V(40, 40)
        self.ring_offset = self.portrait_offset
        self.extra_compact_mode = 2
        self.extra_icon_size = V(40, 40)
        self.extra_start_offset = self.emp_start_offset + V(5, 52)
        self.extra_per_line = 1000
        self.extra_text_offset = V(45, 10)
        self.extra_offset = V(130, 0)
        self.domain_offset = self.extra_start_offset + self.extra_offset * 5
        self.domain_size = V(40, 40)
        self.domain_text_offset = V(self.domain_size.x + 10, 10)

@dataclass(slots=True)
class LayoutArtifact():
    origin : V
    size : V
    margin : int
    offset : V
    portrait_size : V
    portrait_folder : str
    portrait_offset : V
    arousal_icon_size : V
    arousal_icon_offset : V
    ring_size : V
    ring_offset : V
    skill_compact_mode : int
    skill_icon_size : V
    skill_start_offset : V
    skill_per_line : int
    skill_line_jump : int
    skill_text_offset : V
    skill_value_offset : V
    skill_desc_offset : V
    skill_desc_chara_limit : V
    skill_desc_chara_limit_compact : V
    skill_offset : V

    def __init__(self : LayoutArtifact) -> None:
        self.origin = V(0, 0)
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 5)
        self.margin = 5
        self.offset = V(0, self.size.y)
        self.portrait_size = V(196, 408) * (self.size.y  / 408.0)
        self.portrait_folder = "f"
        self.portrait_offset = V(2, 0)
        self.arousal_icon_size = V(60, 60)
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_size = V(60, 60)
        self.ring_offset = self.portrait_offset
        self.skill_compact_mode = 0
        self.skill_icon_size = V(40, 40)
        self.skill_start_offset = V(self.offset.x + self.portrait_size.x + 10, 15)
        self.skill_per_line = 1000
        self.skill_text_offset = V(45, 10)
        self.skill_value_offset = V(100, 10)
        self.skill_desc_offset = V(210, 10)
        self.skill_desc_chara_limit = 50
        self.skill_offset = V(0, 40)

class LayoutArtifactCompact(LayoutArtifact):
    def __init__(self : LayoutArtifactCompact) -> None:
        super().__init__()
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 8)
        self.offset = V(0, self.size.y)
        self.portrait_size = V(self.size.y, self.size.y)
        self.portrait_folder = "s"
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_offset = self.portrait_offset
        self.skill_compact_mode = 1
        self.skill_icon_size = V(40, 40)
        self.skill_start_offset = V(self.offset.x + self.portrait_size.x + 10, 10)
        self.skill_per_line = 2
        self.skill_line_jump = 40
        self.skill_desc_chara_limit = 45
        self.skill_desc_chara_limit_compact = 15
        self.skill_offset = V(380, 0)

class LayoutArtifactVeryCompact(LayoutArtifactCompact):
    def __init__(self : LayoutArtifactVeryCompact) -> None:
        super().__init__()
        self.size = V(IMAGE_SIZE.x, IMAGE_SIZE.y // 11)
        self.offset = V(0, self.size.y)
        self.portrait_size = V(self.size.y, self.size.y)
        self.portrait_folder = "s"
        self.arousal_icon_size = V(40, 40)
        self.arousal_icon_offset = self.portrait_size - self.arousal_icon_size
        self.ring_size = V(40, 40)
        self.ring_offset = self.portrait_offset
        self.skill_compact_mode = 2
        self.skill_icon_size = V(40, 40)
        self.skill_start_offset = V(self.offset.x + self.portrait_size.x + 10, 10)
        self.skill_per_line = 2
        self.skill_line_jump = 40

# Main class
class Mizatube:
    VERSION : str = "1.0"
    BOOKMARK_VERSION : int = 3
    ANY_CHARACTER = [
        "3020072000", # Young cat
        "3030182000", # SR Lyria
        "3040643000", # SSR Lyria
    ]
    # colors
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    PLUS_COLOR = (255, 255, 95)
    MODIFIER_MAX_COLOR = (255, 168, 38, 255)
    AWK_COLOR = (198, 170, 240)
    DOMAIN_COLOR = (100, 210, 255)
    RADIANCE_COLOR = (110, 140, 250)
    SAINT_COLOR = (207, 145, 64)
    COLORS = { # color for estimated advantage, per element
        1:(243, 48, 33),
        2:(85, 176, 250),
        3:(227, 124, 32),
        4:(55, 232, 16),
        5:(253, 216, 67),
        6:(176, 84, 251)
    }
    COLORS_TXT = { # color strings
        1:"Fire",
        2:"Water",
        3:"Earth",
        4:"Wind",
        5:"Light",
        6:"Dark"
    }
    ASSET_TABLE : dict[str, dict[str, str]] = {
        "leader":{
            "squareicon":"assets_en/img/sp/assets/leader/s/{}.jpg",
            "partyicon":"assets_en/img/sp/assets/leader/quest/{}.jpg",
            "fullart":"http://prd-game-a-granbluefantasy.akamaized.net/assets_en/img/sp/assets/leader/my/{}.png",
            "homeart":"assets_en/img/sp/assets/leader/job_change/{}.png",
        },
        "weapon":{
            "squareicon":"assets_en/img/sp/assets/weapon/s/{}.jpg",
            "partyicon":"assets_en/img/sp/assets/weapon/m/{}.jpg",
            "fullart":"assets_en/img/sp/assets/weapon/b/{}.png",
            "homeart":"assets_en/img/sp/assets/weapon/b/{}.png",
        },
        "summon":{
            "squareicon":"assets_en/img/sp/assets/summon/s/{}.jpg",
            "partyicon":"assets_en/img/sp/assets/summon/m/{}.jpg",
            "fullart":"assets_en/img/sp/assets/summon/my/{}.png",
            "homeart":"assets_en/img/sp/assets/summon/b/{}.png",
        },
        "character":{
            "squareicon":"assets_en/img/sp/assets/npc/s/{}.jpg",
            "partyicon":"assets_en/img/sp/assets/npc/quest/{}.jpg",
            "fullart":"assets_en/img/sp/assets/npc/my/{}.png",
            "homeart":"assets_en/img/sp/assets/npc/b/{}.png",
        },
        "skin":{
            "squareicon":"assets/{}",
            "partyicon":"assets/{}",
            "fullart":"assets/{}",
            "homeart":"assets/{}",
        },
        "weapon_open":{
            "squareicon":"assets_en/img/sp/assets/weapon/s/{}.jpg",
            "partyicon":"assets_en/img/sp/deckcombination/base_empty_weapon_sub.png",
            "fullart":"",
            "homeart":"",
        },
        "character_open":{
            "squareicon":"assets_en/img/sp/assets/npc/s/{}.jpg",
            "partyicon":"assets_en/img/sp/deckcombination/base_empty_npc.jpg",
            "fullart":"",
            "homeart":"",
        },
    }
    
    def __init__(self : Mizatube) -> None:
        self.language : str = Language.undefined
        self.font : tuple[ImageFont, ImageFont, ImageFont, ImageFont]|None = None
        self.cache : dict[str, IMG] = {}
        self.client : aiohttp.ClientSession = None # HTTP client
        self.inflight : dict[str, asyncio.Event] = {}
        self.classes : dict[str, str]|None = None
        self.emp_cache : dict = {}
        self.artifact_cache : dict = {}
        self.template : dict|None = None
        self.bosses : dict|None = None
        self.mask : Image|None = None
        self.extra_grid : bool = False
        self.extra_summon : bool = False
        self.thumbnail_fonts : dict[tuple[str, int], ImageFont] = {}
        self.args : dict = {}

    def input(self : Mizatube, text : str = "") -> str:
        if "input" in self.args:
            print(text)
            if len(self.args["input"]) > 0:
                return self.args["input"].pop(0)
            else:
                return ""
        else:
            return input(text)

    def load_fonts(self : Mizatube) -> None:
        match self.language:
            case Language.english:
                self.font = (
                    ImageFont.truetype("assets/font_english.ttf", 20, encoding="unic"),
                    ImageFont.truetype("assets/font_english.ttf", 24, encoding="unic"),
                    ImageFont.truetype("assets/font_english.ttf", 30, encoding="unic"),
                    ImageFont.truetype("assets/font_english.ttf", 45, encoding="unic"),
                )
            case _:
                raise Exception("Unsupported language")

    # retrieve font from cache or load it
    def load_thumbnail_font(
        self : Mizatube,
        font_file : str, font_size : int,
        *, disable_cache : bool = False
    ) -> ImageFont:
        key : tuple[str, int] = (font_file, font_size)
        if key not in self.thumbnail_fonts:
            if disable_cache:
                return ImageFont.truetype(font_file, font_size, encoding="unic")
            else:
                self.thumbnail_fonts[key] = ImageFont.truetype(font_file, font_size, encoding="unic")
        return self.thumbnail_fonts[key]

    def load_bosses(self : Mizatube) -> None:
        if self.bosses is None:
            try:
                with open("json/boss.json", mode="r", encoding="utf-8") as f:
                    self.bosses = json.load(f)
            except:
                self.bosses = {}

    def load_emp(self : Mizatube, chara_id : str) -> dict:
        if chara_id in self.emp_cache:
            return self.emp_cache[chara_id]
        else:
            with open(f"emp/{chara_id}.json", mode="r", encoding="utf-8") as f:
                self.emp_cache[chara_id] = json.load(f)
                return self.emp_cache[chara_id]

    def load_artifact(self : Mizatube, chara_id : str) -> dict:
        if chara_id in self.artifact_cache:
            return self.artifact_cache[chara_id]
        else:
            with open(f"artifact/{chara_id}.json", mode="r", encoding="utf-8") as f:
                self.artifact_cache[chara_id] = json.load(f)
                return self.artifact_cache[chara_id]

    async def fetch(self : Mizatube, path : str) -> IMG:
        if self.language == Language.japanese:
            path = path.replace('assets_en', 'assets')
        # check cache
        data : bytes = self.cache.get(path, None)
        if data is None:
            if path.startswith("file:"):
                with open(path[len("file:"):], mode="rb") as f:
                    self.cache[path] =  IMG(f.read())
            else:
                # wait ongoing requests
                if path in self.inflight:
                    await self.inflight[path].wait()
                try:
                    with open("cache/" + b64encode(path.encode('utf-8')).decode('utf-8'), mode="rb") as f:
                        self.cache[path] = IMG(f.read())
                except:
                    self.inflight[path] = asyncio.Event()
                    try:
                        io : bytes = await self.get(path)
                        self.cache[path] = IMG(io)
                        try:
                            with open("cache/" + b64encode(path.encode('utf-8')).decode('utf-8'), mode="wb") as f:
                                f.write(io)
                        except Exception as e:
                            print(pexc(e))
                            pass
                    except:
                        pass
                    finally:
                        self.inflight[path].set()
                        del self.inflight[path]
            return self.cache.get(path, None)
        else:
            return data

    async def get(self : Mizatube, path : str) -> bytes:
        response : aiohttp.Response = await self.client.get(
            CDN + path,
            headers={'connection':'keep-alive'}
        )
        async with response:
            if response.status != 200:
                raise Exception(f"HTTP Error code {response.status} for path: {path}")
            return await response.read()

    # subroutine of find_mc_file
    async def find_mc_file_sub(self : Mizatube, job_id : str, mh : str) -> str|None:
        response : aiohttp.Response = await self.client.head(
            f"https://prd-game-a-granbluefantasy.akamaized.net/assets_en/img/sp/assets/leader/s/{job_id}_{mh}_0_01.jpg"
        )
        async with response:
            return None if response.status != 200 else mh

    async def find_mc_file(self : Mizatube, job_id : str, appearence : str) -> str:
        if self.classes is None:
            try:
                with open("json/classes.json", mode="r", encoding="utf-8") as f:
                    self.classes = json.load(f)
            except:
                self.classes = {}
        job_id = str((int(job_id) // 100) * 100 + 1)
        if job_id not in self.classes:
            tasks = []
            # look for job MH
            for mh in ["sw", "kn", "sp", "ax", "wa", "gu", "me", "bw", "mc", "kr"]:
                tasks.append(self.find_mc_file_sub(job_id, mh))
            for r in await asyncio.gather(*tasks):
                if r is not None:
                    self.class_modified = True
                    self.classes[job_id] = r
                    try:
                        with open("json/classes.json", mode="w", encoding="utf-8") as f:
                            json.dump(self.classes, f, indent=0)
                    except:
                        pass
        return f"{job_id}_{self.classes[job_id]}_{'_'.join(appearence.split('_')[2:])}"

    def find_chara_file(self : Mizatube, chara_id : str, lvl : str, evolution : str, style : str, mc_element : str) -> tuple[str, str]:
        ilvl : int = int(lvl)
        ievo : int = int(evolution)
        uncap : str
        star : str
        if ievo >= 6:
            uncap = "04"
            if ilvl > 140:
                star = "star_4_5"
            elif ilvl > 130:
                star = "star_4_4"
            elif ilvl > 120:
                star = "star_4_3"
            elif ilvl > 110:
                star = "star_4_2"
            else:
                star = "star_4_1"
        elif ievo >= 5:
            uncap = "03"
            star = "star_2"
        elif ievo >= 2:
            uncap = "02"
            star = "star_1"
        else:
            uncap = "01"
            star = "star_0"
        if style != "1":
            style = f"_st{style}"
            uncap = "01"
        else:
            style = ""
        if chara_id in self.ANY_CHARACTER:
            return f"{chara_id}_{uncap}{style}_0{mc_element}", star
        else:
            return f"{chara_id}_{uncap}{style}", star

    def valid_name(self : Mizatube, s : str) -> bool:
        for c in s:
            if c not in "abcdefghijklmnopqrstuvwxyz0123456789_":
                return False
        return True

    async def make_boss_background(self : Mizatube, boss_data : dict) -> IMG|None:
        try:
            eid : str = boss_data["id"]
            suffix : str
            background : str = boss_data["background"]
            icon : str = boss_data["icon"]
            if "_" in eid:
                # if underscore in enemy id, get suffix (only used for old Hexachromatic spoiler animation and some event bosses)
                suffix = "_" + eid.split("_")[1]
                eid = eid.split("_")[0]
            else:
                suffix = ""
            # retrieve background
            bg_img : IMG|None = None
            if background is not None:
                bg_img = IMG(
                    await self.get(f"assets_en/img/sp/raid/bg/{background}.jpg")
                )
                # resize it to fit the thumbnail
                mod : float = 1280 / bg_img.image.size[0]
                bg_img = bg_img.resize(V(bg_img.image.size[0] * mod, bg_img.image.size[0] * mod))
                # calculate and apply a crop to show somehow the middle part
                y : int = (bg_img.image.size[1] // 2) - 360
                bg_img = bg_img.crop((0, y, 1280, y + 720))

            # make image (youtube wants 720p thumbnail usually)
            img : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
            # retrieve animation file
            cjs : str = (await self.get(f"assets_en/js/cjs/raid_appear_{eid}{suffix}.js")).decode('utf-8')
            # load spritsheet file (this type of animation usually only use one, so we don't bother checking. It could break in the future for more fancier bosses)
            appear : IMG = IMG(await self.get(f"assets_en/img/sp/cjs/raid_appear_{eid}{suffix}.png"))
            # generate image
            parser = CreateJSTimelineParser(f"raid_appear_{eid}{suffix}", cjs, appear)
            render : IMG = parser.render()
            # apply the gradient mask
            if self.mask is None:
                tmp : Image = Image.open("assets/mask.png").convert('L')
                self.mask = tmp.convert('L')
                tmp.close()
            grad : IMG = IMG.new_canvas(GBF_SIZE)
            render = IMG(Image.composite(render.image, grad.image, self.mask))
            # paste render
            img.paste_transparency(render.resize(GBF_SIZE * (680 / (1.0 * GBF_SIZE.y))), V.ZERO())
            
            # if a background if selected, add it behind
            if bg_img is not None:
                bg_img.paste_transparency(img, V.ZERO())
                img.swap(bg_img)
            try: # add the icon (if set)
                if icon is not None:
                    ico_img : IMG = IMG(await self.get(f"assets_en/img/sp/assets/enemy/m/{icon}.png"))
                    layer : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
                    # position: bottom left corner, off 15px
                    layer.paste_transparency(ico_img, V(15, 720 - ico_img.image.size[1] - 15))
                    img = img.alpha(layer)
            except Exception as e:
                print(pexc(e))
            return img
        except Exception as me:
            print(pexc(me))
            return None

    async def draw_thumbnail_background(self : Mizatube, img : IMG, action : dict) -> None:
        if "boss" not in action:
            return
        bg : IMG = await self.make_boss_background(action["boss"])
        if bg is None:
            return
        img.swap(img.alpha(bg))

    async def get_element_size(
        self : Mizatube,
        asset : str, display : str
    ) -> tuple[V|None, str|None]: # retrive an element asset and return its size and path
        try:
            path : str
            if not asset.startswith(("file:", "asset")):
                # GBF portraits
                key : str
                if asset == "1999999999":
                    key = "weapon_open"
                elif asset == "3999999999":
                    key = "character_open"
                else:
                    try:
                        if len(asset.replace('skin/', '').split('_')[0]) < 10:
                            raise Exception("MC?")
                        int(asset.replace('skin/', '').split('_')[0])
                        match int(asset.replace('skin/', '')[0]):
                            case 1:
                                key = "weapon"
                            case 2:
                                key = "summon"
                            case 3:
                                key = "character"
                            case _:
                                raise Exception("Unknown")
                    except Exception as e:
                        if str(e) == "MC?":
                            if len(asset.split("_")) != 4:
                                key = "skin"
                            else:
                                key = "leader"
                        else:
                            key = "skin"
                try:
                    path = self.ASSET_TABLE[key][display].format(asset)
                except:
                    path = self.ASSET_TABLE[key][display]
            else:
                path = asset
            if path.startswith("file:"):
                im : IMG = IMG(path[len("file:"):])
                size : V = V(*(im.image.size))
                return size, path
            else:
                im : IMG = IMG(await self.fetch(path))
                size : V = V(*(im.image.size))
                return size, path
        except:
            return None, None

    async def draw_images(
        self : Mizatube,
        img : IMG, assets : list[str] = [],
        anchor : str = "middle", offset : V = V(0, 0),
        ratio : float = 1.0, display : str = "squareicon",
        fixedsize : V|None = None
    ) -> None:
        position : V
        match anchor.lower():
            case "topleft":
                position = V(0, 0)
            case "top":
                position = V(640, 0)
            case "topright":
                position = V(1280, 0)
            case "right":
                position = V(1280, 360)
            case "bottomright":
                position = V(1280, 720)
            case "bottom":
                position = V(640, 720)
            case "bottomleft":
                position = V(0, 720)
            case "left":
                position = V(0, 360)
            case "middle":
                position = V(640, 360)
        position = position + offset
        for asset in assets:
            size, path = await self.get_element_size(asset, display)
            if size is None:
                continue
            if fixedsize is not None:
                size = fixedsize
            size = size * ratio
            match anchor.lower():
                case "topright":
                    position += V(- size[0].x, 0)
                case "right":
                    position += V(- size.x, 0)
                case "bottomright":
                    position += - size
                case "bottom":
                    position += V(0, - size.y)
                case "bottomleft":
                    position += V(0, - size.y)
            img.paste_transparency(
                (await self.fetch(path)).resize(size),
                position
            )
            position = position + V(size.x, 0)

    async def draw_thumbnail_asset(self : Mizatube, img : IMG, action : dict) -> None:
        if action.get("asset", None) is None:
            return img
        anchor : str = action.get('anchor', 'topleft')
        offset : tuple[int, int] = action.get('position', (0,0))
        ratio : float = action.get('size', 1.0)
        await self.draw_images(img, [action["asset"]], anchor, offset, ratio)

    # add the party to the image
    async def draw_thumbnail_party(self : Mizatube, img : IMG, action : dict, party : dict) -> None:
        entries : list[str] = []
        noskin : bool = action.get("noskin", False)
        mainsummon : bool = action.get("mainsummon", False)
        mode : str
        nchara : int
        try:
            if len(party["deck"]["npc"]) > 8:
                mode = "babyl"
                nchara = 11
            elif len(party["deck"]["npc"]) > 5:
                mode = "unlimited"
                nchara = 8
            else:
                mode = "normal"
                nchara = 5
            # retrieve mc
            if not mainsummon:
                if noskin:
                    entries.append(
                        await self.find_mc_file(
                            party["deck"]["pc"]["job"]["master"]["id"],
                            party["deck"]["pc"]["param"]["image"]
                        )
                    )
                else:
                    entries.append(party["deck"]["pc"]["param"]["image"])
            # iterate over entries and add their file to the list
            for i in range(1, nchara + 1):
                if mainsummon:
                    break
                chara_data : dict = party["deck"]["npc"][str(i)]
                if chara_data["master"] is None:
                    entries.append("3999999999")
                    continue
                if noskin:
                    chara_file : str
                    chara_file, _ = self.find_chara_file(
                        chara_data["master"]["id"],
                        chara_data["param"]["level"],
                        chara_data["param"]["evolution"],
                        chara_data["param"]["style"],
                        party["deck"]["pc"]["param"]["attribute"]
                    )
                    entries.append(chara_file)
                else:
                    entries.append(chara_data["param"]["image_id_3"])
            if not mainsummon:
                # retrieve main hand weapon
                if party["deck"]["pc"]["weapons"]["1"]["param"] is not None:
                    entries.append(party["deck"]["pc"]["weapons"]["1"]["param"]["image_id"])
                else:
                    entries.append("1999999999")
            # retrieve main summon
            if party["deck"]["pc"]["summons"]["1"]["param"] is not None:
                entries.append(party["deck"]["pc"]["summons"]["1"]["param"]["image_id"])
            if not mainsummon:
                # retrieve support summon
                if party["support_summon"] is not None:
                    entries.append(party["support_summon"])
                else:
                    entries.append("1999999999")
        except Exception as e:
            print("An error occured while importing a party:")
            print(pexc(e))
            raise Exception("Failed to import party data")
        # now, we add each element at the given position, on a different format depending on mode and babyl flag
        anchor = action.get('anchor', 'topleft')
        offset = V(*action.get('position', (0,0)))
        ratio = action.get('size', 1.0)
        if mainsummon:
            await self.draw_images(img, entries, anchor, offset, ratio, "partyicon")
        elif mode == "babyl":
            # Party 1
            await self.draw_images(
                img, entries[:4], anchor,
                offset,
                ratio, "squareicon", V(100, 100)
            )
            # Party 2
            await self.draw_images(
                img, entries[4:8], anchor,
                offset + V(0, 100) * ratio,
                ratio, "squareicon", V(100, 100)
            )
            # Party 3
            await self.draw_images(
                img, entries[8:12], anchor,
                offset + V(0, 200) * ratio,
                ratio, "squareicon", V(100, 100)
            )
            # Main Weapon
            await self.draw_images(
                img, entries[12:13], anchor,
                offset + V(0, 310) * ratio,
                ratio, "partyicon", V(130, 73)
            )
            # Main Summon
            await self.draw_images(
                img, entries[13:14], anchor,
                offset + V(130 + 6, 310) * ratio,
                ratio, "partyicon", V(130, 73)
            )
            # Support Summon
            await self.draw_images(
                img, entries[14:15], anchor,
                offset + V((130 + 6) * 2, 310) * ratio,
                ratio, "partyicon", V(130, 73)
            )
        elif mode == "unlimited":
            # Note: Elevated by 58 pixels so it fits on most normal party templates
            # Frontline
            await self.draw_images(
                img, entries[:4], anchor,
                offset + V(47, -58) * ratio,
                ratio, "squareicon",
                V(95, 95)
            )
            # Backline
            await self.draw_images(
                img, entries[4:9], anchor,
                offset + V(0, -58 + 95 + 10) * ratio,
                ratio, "squareicon", V(95, 95)
            )
            # Main Weapon
            await self.draw_images(
                img, entries[9:10], anchor,
                offset + V(5, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )
            # Main Summon
            await self.draw_images(
                img, entries[10:11], anchor,
                offset + V(5 + 150 + 8, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )
            # Support summon
            await self.draw_images(
                img, entries[11:12], anchor,
                offset + V(5 + (150 + 8) * 2, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )
        else:
            # Frontline
            await self.draw_images(
                img, entries[:4], anchor,
                offset,
                ratio, "partyicon", V(78, 142)
            )
            # Backline
            await self.draw_images(
                img, entries[4:6], anchor,
                offset + V(78 * 4 + 15, 0) * ratio,
                ratio, "partyicon", V(78, 142)
            )
            # Main Weapon
            await self.draw_images(
                img, entries[6:7], anchor,
                offset + V(5, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )
            # Main Summon
            await self.draw_images(
                img, entries[7:8], anchor,
                offset + V(5 + 150 + 10, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )
            # Support summon
            await self.draw_images(
                img, entries[8:9], anchor,
                offset + V(5 + (150 + 10) * 2, 142 + 10) * ratio,
                ratio, "partyicon", V(150, 85)
            )

    # apply justifications and calculate bounds
    def generate_text(
        self : Mizatube,
        text : str, font : ImageFont,
        fs : int, os : int, lj : int, rj : int
    ) -> tuple[str, list[int]]:
        nl = text.split('\n')
        size = [0, 0]
        for i in range(len(nl)):
            if lj > 0:
                nl[i] = nl[i].ljust(lj)
            if rj > 0:
                nl[i] = nl[i].rjust(rj)
            s = font.getbbox(nl[i], stroke_width=os)
            size[0] = max(size[0], s[2] - s[0])
            size[1] += s[3] - s[1] + 10
        # adjust
        size[1] = int(size[1] * 1.15)
        return '\n'.join(nl), size

    # get a text position on screen
    def get_text_position(
        self : Mizatube,
        anchor : str,
        size : list[int],
        offset : V|tuple = (0, 0)
    ) -> V:
        text_pos : V
        match anchor.lower():
            case "topleft":
                text_pos = V(0, 0)
            case "top":
                text_pos = V(640 - size[0] // 2, 0)
            case "topright":
                text_pos = V(1280 - size[0], 0)
            case "right":
                text_pos = V(1280 - size[0], 360 - size[1] // 2)
            case "bottomright":
                text_pos = V(1280 - size[0], 720 - size[1])
            case "bottom":
                text_pos = V(640 - size[0] // 2, 720 - size[1])
            case "bottomleft":
                text_pos = V(0, 720 - size[1])
            case "left":
                text_pos = V(0, 360 - size[1] // 2)
            case "middle":
                text_pos = V(640 - size[0] // 2, 360 - size[1] // 2)
        return text_pos + offset

    # generate a gradient (for texts)
    def generate_gradient(
        self : Mizatube,
        position : V, size : list[int],
        gcol1 : tuple[int, int, int], gcol2 : tuple[int, int, int]
    ) -> IMG:
        img : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
        px = img.image.load()
        for y in range(0, size[1]):
            color = tuple(int(gcol1[i] + (gcol2[i] - gcol1[i]) * y / size[1]) for i in range(3))
            try:
                for x in range(0, size[0]):
                    px[position.x + x, position.y + y] = color
            except:
                pass
        return img

    def draw_thumbnail_text_gradient(
        self : Mizatube,
        img : IMG,
        text : str = "",
        gcol1 : tuple[int, int, int] = (255, 255, 255),
        gcol2 : tuple[int, int, int] = (255, 255, 255),
        fc : tuple[int, int, int] = (255, 255, 255),
        oc : tuple[int, int, int] = (0, 0, 0),
        os : int = 10,
        bold : bool = False,
        italic : bool = False,
        anchor : str = "middle",
        offset : V|tuple = (0, 0),
        fs : int = 24,
        lj : int = 0,
        rj : int = 0
    ) -> None: # to draw text into an image
        # generate mask
        img_text : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
        self.draw_thumbnail_text_standard(img_text, text, (255, 255, 255), (0, 0, 0, 0), os, bold, italic, anchor, offset, fs, lj, rj)
        # get text size and position
        font_file = "assets/thumbnail_font"
        if bold:
            font_file += "b"
        if italic:
            font_file += "i"
        font_file += ".ttf"
        font = self.load_thumbnail_font(font_file, fs)
        _, size = self.generate_text(text.replace('\\n', '\n'), font, fs, os, lj, rj)
        text_pos = self.get_text_position(anchor, size, offset)
        # generate a gradient
        grad : IMG = self.generate_gradient(text_pos, size, gcol1, gcol2)
        # draw text with outline
        self.draw_thumbnail_text_standard(img, text, fc, oc, os, bold, italic, anchor, offset, fs, lj, rj)
        # paste gradient with text mask on top
        img.image.paste(grad.image, (0, 0), img_text.image)

    # add text on the canvas
    def draw_thumbnail_text_standard(
        self : Mizatube,
        img : IMG,
        text : str = "",
        fc : tuple[int, int, int] = (255, 255, 255),
        oc : tuple[int, int, int] = (0, 0, 0),
        os : int = 10,
        bold : bool = False,
        italic : bool = False,
        anchor : str = "middle",
        offset : V|tuple = (0, 0),
        fs : int = 24,
        lj : int = 0,
        rj : int = 0
    ) -> None: # to draw text into an image
        text = text.replace('\\n', '\n')
        font_file = "assets/thumbnail_font"
        if bold:
            font_file += "b"
        if italic:
            font_file += "i"
        font_file += ".ttf"
        font = self.load_thumbnail_font(font_file, fs)
        text, size = self.generate_text(text, font, fs, os, lj, rj)
        text_pos = self.get_text_position(anchor, size, offset)
        img.text(text_pos, text, fill=fc, font=font, stroke_width=os, stroke_fill=oc)

    # add the party to the image
    async def draw_thumbnail_text(self : Mizatube, img : IMG, action : dict) -> None:
        text = action.get("string", '')
        if text == '':
            return
        fc : tuple[int, ...] = tuple(action.get('fontcolor', (255, 255, 255)))
        oc : tuple[int, ...]  = tuple(action.get('outlinecolor', (255, 0, 0)))
        os : int = action.get('outlinesize', 10)
        bold : bool = action.get('bold', False)
        italic : bool = action.get('italic', False)
        anchor : str = action.get('anchor', 'middle')
        offset : tuple[int, int] = action.get('position', (0, 0))
        fs : int = action.get('fontsize', 120)
        ll : int = action.get('lengthlimit', 0)
        if ll > 0:
            max_length : int = 0
            for line in text.split("\\n"):
                max_length = max(len(line), max_length)
            if max_length > ll:
                fs = int(fs * (1 - (max_length - ll) / ll))
        if action.get('multilinelimit', False):
            nl_count : int = text.count("\\n")
            if nl_count > 0:
                fs = int(fs / (nl_count + 1))
        if 'maxwidth' in action:
            # get largest line
            maxline : str = ""
            slen : int = 0
            for i, line in enumerate(text.split("\\n")):
                if len(line) > slen:
                    maxline = line
            # calculate font width
            font_file : int = "assets/thumbnail_font"
            if bold:
                font_file += "b"
            if italic:
                font_file += "i"
            font_file += ".ttf"
            while True:
                font : ImageFont = self.load_thumbnail_font(font_file, fs, disable_cache=True)
                s : tuple = font.getbbox(maxline, stroke_width=os)
                w : int = s[2] - s[0]
                if w < action["maxwidth"]:
                    break
                else:
                    fs -= 1
        lj = action.get('ljust', 0)
        rj = action.get('rjust', 0)
        text_img : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
        if action.get('gradient', None) is not None:
            self.draw_thumbnail_text_gradient(text_img, text, action['gradient'][0], action['gradient'][1], fc, oc, os, bold, italic, anchor, offset, fs, lj, rj)
        else:
            self.draw_thumbnail_text_standard(text_img, text, fc, oc, os, bold, italic, anchor, offset, fs, lj, rj)
        if action.get('rotate', None) is not None:
            if len(action['rotate']) == 2:
                text_img = text_img.rotate(action['rotate'][0], center=tuple(action['rotate'][1]))
            else:
                text_img = text_img.rotate(action['rotate'][0])
        img.paste(text_img, V.ZERO())

    async def draw_thumbnail(self : Mizatube, party : dict, template : dict) -> None:
        img : IMG = IMG.new_canvas(THUMBNAIL_SIZE)
        for i, action in enumerate(template):
            match action["type"]:
                case "background":
                    await self.draw_thumbnail_background(img, action)
                case "boss":
                    if "boss" in action:
                        action["boss"]["background"] = None
                    await self.draw_thumbnail_background(img, action)
                case "party":
                    await self.draw_thumbnail_party(img, action, party)
                case "asset":
                    await self.draw_thumbnail_asset(img, action)
                case "textinput":
                    await self.draw_thumbnail_text(img, action)
                case _:
                    pass
        img.save("output_thumbnail.png", self.args["dry"])
        print("Thumbnail generated with success.")

    def thumbnail_select_template(self : Mizatube) -> list|None:
        print("Please select a template:")
        choices = []
        for k in self.template:
            print(f"[{len(choices)}] {k}")
            choices.append(k)
        print("[Any] Cancel")
        s : str = self.input()
        k : str
        try:
            k = choices[int(s)]
        except:
            return None
        return copy.deepcopy(self.template[k])

    def save_boss_json(self : Mizatube) -> None:
        self.load_bosses()
        try:
            with open("json/boss.json", mode="w", encoding="utf-8") as f:
                json.dump(self.bosses, f, indent=0)
        except:
            pass

    def search_boss(self : Mizatube, search : str) -> list[str]:
        self.load_bosses()
        s = search.lower().split(" ")
        r = []
        for k in self.bosses:
            for i in s:
                if i != "" and i in k:
                    r.append(k)
                    break
        return r

    def process_boss_json(self : Mizatube, json_string : str) -> dict|None:
        try:
            data = json.loads(json_string)
            data.pop("ver", None)
            return data
        except:
            pass
        return None

    def register_boss(self : Mizatube, data : dict) -> None:
        self.load_bosses()
        while True:
            print("Input a boss name to save those settings (Leave blank to ignore)")
            s = self.input().lower()
            if s == "":
                break
            elif s in self.bosses:
                print(s, "already exists, overwrite? ('y' to confirm)")
                if self.input().lower() != 'y':
                    continue
            self.bosses[s] = data
            self.save_boss_json()
            print(s, "registered")
            break

    def thumbnail_select_boss(self : Mizatube, action : dict) -> None:
        self.load_bosses()
        while True:
            print(f"Input the {action["type"]} you want to use (Leave blank to ignore)")
            s = self.input().lower()
            if s == "":
                break
            else:
                data : str = self.process_boss_json(s)
                if data is not None and data["id"] is not None:
                    action["boss"] = data
                    if "input" not in self.args:
                        self.register_boss(data)
                else:
                    if s not in self.bosses:
                        print(s, "not found in the boss data")
                        r = self.search_boss(s)
                        if len(r) > 0:
                            print("Did you mean...?")
                            print("*", "\n* ".join(r))
                        if "input" in self.args:
                            break
                    else:
                        action["boss"] = self.bosses[s]
                        break

    def thumbnail_select_auto_mode(self : Mizatube, action : dict) -> None:
        print("Select an Auto setting:")
        print("[0] Auto")
        print("[1] Full Auto")
        print("[2] Full Auto Guard")
        print("[Any] Manual")
        match self.input():
            case "0":
                action["asset"] = "file:assets/auto.png"
            case "1":
                action["asset"] = "file:assets/fa.png"
            case "2":
                action["asset"] = "file:assets/fa_guard.png"
            case _:
                action["asset"] = None
        action["type"] = "asset"

    def thumbnail_select_nightmare(self : Mizatube, action : dict) -> None:
        POSSIBLE : list[dict] = [
            {"text":"GW NM90", "event":"gw", "id":"90"},
            {"text":"GW NM95", "event":"gw", "id":"95"},
            {"text":"GW NM100", "event":"gw", "id":"100"},
            {"text":"GW NM150", "event":"gw", "id":"150"},
            {"text":"GW NM200", "event":"gw", "id":"200"},
            {"text":"GW NM250", "event":"gw", "id":"250"},
            {"text":"DB 1*", "event":"db_star", "id":"1"},
            {"text":"DB 2*", "event":"db_star", "id":"2"},
            {"text":"DB 3*", "event":"db_star", "id":"3"},
            {"text":"DB 4*", "event":"db_star", "id":"4"},
            {"text":"DB 5*", "event":"db_star", "id":"5"},
            {"text":"DB UF95", "event":"db_strong", "id":"1"},
            {"text":"DB UF135", "event":"db_strong", "id":"2"},
            {"text":"DB UF175", "event":"db_strong", "id":"3"},
            {"text":"DB UF215", "event":"db_strong", "id":"4"},
            {"text":"DB Valiant", "event":"db_valiant", "id":"4"},
            {"text":"Record NM100", "event":"record", "id":"100"},
            {"text":"Record NM150", "event":"record", "id":"150"},
        ]
        print("Select a GW NM or DB Foe:")
        for i, fight in enumerate(POSSIBLE):
            print(f"[{i}] {fight["text"]}")
        print("[Any] Skip")
        s : str = self.input().lower()
        fight_id : int
        event_id : int
        try:
            fight_id = int(s)
            if fight_id < 0 or fight_id >= len(POSSIBLE):
                raise Exception()
        except:
            return
        while True:
            print("Input a GW / DB / Record ID:")
            try:
                event_id = int(self.input())
                if event_id < 0 or event_id > 200:
                    raise Exception()
                break
            except:
                if "input" in self.args:
                    return
        match POSSIBLE[fight_id]["event"]:
            case "gw":
                action["asset"] = f"assets_en/img/sp/event/teamraid{event_id:03}/assets/thumb/teamraid{event_id:03}_hell{POSSIBLE[fight_id]["id"]}.png"
            case "db_star":
                action["asset"] = f"assets_en/img/sp/assets/summon/qm/teamforce{event_id:02}_star{POSSIBLE[fight_id]["id"]}.png"
            case "db_strong":
                action["asset"] = f"assets_en/img/sp/assets/summon/qm/teamforce{event_id:02}_strong{POSSIBLE[fight_id]["id"]}.png"
            case "db_valiant":
                action["asset"] = f"assets_en/img/sp/assets/summon/qm/teamforce{event_id:02}_sp.png"
            case "record":
                action["asset"] = f"assets_en/img/sp/event/common/terra/top/assets/quest/terra{event_id:03}_hell{POSSIBLE[fight_id]["id"]}.png"
        action["type"] = "asset"

    def thumbnail_select_ascendant(self : Mizatube, action : dict) -> None:
        print("Select a Difficulty:")
        print("[0] Proud")
        print("[Any] Proud+")
        if self.input() == "0":
            p = ""
        else:
            p = "plus"
        print("Input Pride Number:")
        print("[1] Gilbert")
        print("[2] Nalhe Great Wall")
        print("[3] Violet Knight")
        print("[4] Echidna")
        print("[5] Golden Knight")
        print("[6] White Knight")
        print("[7] Cherub")
        print("[8] Kikuri")
        print("[9] Zwei")
        print("[10] Maxwell")
        print("[11] Otherworld Violet Knight")
        print("[Any] Anything Else")
        pn = self.input().zfill(3)
        action["asset"] = f"assets_en/img/sp/quest/assets/free/conquest_{pn:03}_proud{p}.png"
        action["type"] = "asset"

    async def process_thumbnail(self : Mizatube, data : dict) -> None:
        if self.template is None:
            try:
                with open("json/template.json", mode="r", encoding="utf-8") as f:
                    self.template = json.load(f)
                if len(self.template) == 0:
                    return
            except:
                return
        self.load_bosses()
        template : list|None = self.thumbnail_select_template()
        if template is None:
            return
        # iterate over actions to set their user settings
        for i, action in enumerate(template):
            match action["type"]:
                case "background"|"boss":
                    self.thumbnail_select_boss(action)
                case "autoinput":
                    self.thumbnail_select_auto_mode(action)
                case "nminput": # NM selection
                    self.thumbnail_select_nightmare(action)
                case "prideinput": # pride selection
                    self.thumbnail_select_ascendant(action)
                case "textinput": # text input
                    print(f"Input the '{action["ref"]}'")
                    action["string"] = self.input()
        await self.draw_thumbnail(data["party"], template)

    def process_emp(self : Mizatube, data : dict) -> None:
        if 'emp' not in data or 'id' not in data or 'ring' not in data or (0 > data.get('ver', -1) >= self.BOOKMARK_VERSION):
            raise Exception("Invalid EMP data, check your bookmark!")
        if data['lang'] != Language.english:
            raise Exception("Unsupported language")
        folder : Path = Path("emp")
        if not folder.exists():
            folder.mkdir()
        with open(f"emp/{data['id']}.json", mode='w', encoding="utf-8") as outfile:
            json.dump(data, outfile)
        print(f"EMP saved to {data['id']}.json")

    def process_artifact(self : Mizatube, data : dict) -> None:
        if 'artifact' not in data or (0 > data.get('ver', -1) >= self.BOOKMARK_VERSION):
            raise Exception("Invalid Artifact data, check your bookmark!")
        if data['lang'] != Language.english:
            raise Exception("Unsupported language")
        if 'img' not in data["artifact"] or 'skills' not in data["artifact"]:
            print("Note: No Artifact equipped")
        else:
            data["artifact"]['img'] = data["artifact"]['img'].split('/')[-1]
            for i in range(len(data["artifact"]['skills'])):
                data["artifact"]['skills'][i]['icon'] = "assets" + data["artifact"]['skills'][i]['icon'].split('/assets', 1)[1]
                data["artifact"]['skills'][i]['lvl'] = data["artifact"]['skills'][i]['lvl'].split(' ')[-1]
        folder : Path = Path("artifact")
        if not folder.exists():
            folder.mkdir()
        with open(f"artifact/{data['id']}.json", mode='w', encoding="utf-8") as outfile:
            json.dump(data, outfile)
        print(f"Artifact saved to {data['id']}.json")

    async def draw_party(self : Mizatube, img : IMG, party : dict) -> None:
        # Select layout
        layout : LayoutPartyBase
        if len(party["deck"]["npc"]) > 8:
            layout = LayoutPartyBabyl()
        elif len(party["deck"]["npc"]) > 5:
            layout = LayoutPartyUnlimited()
        else:
            layout = LayoutPartyNormal()
        # Draw background
        img.paste_transparency(
            (await self.fetch("file:assets/bg_1.png")).ninepatch(layout.bg_size, layout.bg_margin),
            layout.origin
        )
        # Draw box
        for (position, count, _) in layout.party_groups:
            img.paste(
                (
                    await self.fetch(
                        "file:assets/box.png"
                    )
                ).ninepatch(
                    V(
                        layout.portrait_size.x * count + layout.box_margin * 2,
                        layout.portrait_size.y + layout.box_margin * 2 + (layout.name_box_size.y if layout.show_name else 0)
                    ),
                    layout.box_margin
                ),
                position - layout.box_margin
            )
        # Draw portraits
        for (i, position, text) in layout.groups(len(party["deck"]["npc"]) + 1):
            if i == 0:
                name = party["deck"]["pc"]["job"]["master"]["name"]
                # Draw MC
                mc_file : str = await self.find_mc_file(
                    party["deck"]["pc"]["job"]["master"]["id"],
                    party["deck"]["pc"]["param"]["image"]
                )
                img.paste(
                    (await self.fetch(f"assets_en/img/sp/assets/leader/s/{mc_file}.jpg")).resize(layout.portrait_size),
                    position
                )
                img.paste_transparency(
                    (await self.fetch(f"assets_en/img/sp/ui/icon/job/{party["deck"]["pc"]["job"]["master"]["id"]}.png")).resize(layout.job_icon_size),
                    position + layout.portrait_icon_offset
                )
                if party["deck"]["pc"]["job"]["param"]["perfection_proof_level"] == 6:
                    img.paste_transparency(
                        (await self.fetch("assets_en/img/sp/ui/icon/job/ico_perfection.png")).resize(layout.job_icon_size),
                        position + layout.portrait_icon_offset + V(0, layout.job_icon_size.y,)
                    )
                
            else:
                # Draw character
                chara_data : dict = party["deck"]["npc"][str(i)]
                if chara_data["master"] is None:
                    img.paste(
                        (await self.fetch("assets_en/img/sp/tower/assets/npc/s/3999999999.jpg")).resize(layout.portrait_size),
                        position
                    )
                    continue
                
                name = chara_data["master"]["short_name"]
                chara_file : str
                star_file : str
                chara_file, star_file = self.find_chara_file(
                    chara_data["master"]["id"],
                    chara_data["param"]["level"],
                    chara_data["param"]["evolution"],
                    chara_data["param"]["style"],
                    party["deck"]["pc"]["param"]["attribute"]
                )
                img.paste(
                    (await self.fetch(f"assets_en/img/sp/assets/npc/s/{chara_file}.jpg")).resize(layout.portrait_size),
                    position
                )
                img.paste_transparency(
                    (await self.fetch(f"file:assets/{star_file}.png")).resize(layout.star_icon_size),
                    position + layout.portrait_icon_offset
                )
                # awakening
                if chara_data["param"]["npc_arousal_form"] is not None:
                    img.paste_transparency(
                        (await self.fetch(f"assets_en/img/sp/ui/icon/npc_arousal_form/form_{chara_data["param"]["npc_arousal_form"]}.png")).resize(layout.arousal_icon_size),
                        position + layout.portrait_size - layout.arousal_icon_size
                    )
                # plus marks
                if chara_data["param"]["quality"] != "0":
                    img.text(
                        position + layout.plus_offset,
                        f"+{chara_data["param"]["quality"]}",
                        fill=self.PLUS_COLOR,
                        font=self.font[2],
                        stroke_width=6,
                        stroke_fill=self.BLACK
                    )
                # ring
                if chara_data["param"]["has_npcaugment_constant"]:
                    img.paste_transparency(
                        (await self.fetch("assets_en/img/sp/ui/icon/augment2/icon_augment2_l.png")).resize(layout.ring_size),
                        position + layout.ring_offset
                    )
            if layout.show_name:
                img.paste(
                    (await self.fetch("file:assets/bg_text.png")).ninepatch(layout.name_box_size, 1),
                    position + V(0, layout.portrait_size.y)
                )
                if len(name) > layout.name_character_limit:
                    name = name[:layout.name_character_limit] + "..."
                img.text(
                    position + V(0, layout.portrait_size.y) + layout.name_offset,
                    name,
                    fill=self.WHITE,
                    font=self.font[1]
                )
            if text != "":
                img.paste_transparency(
                    (await self.fetch(f"file:assets/{text}.png")),
                    position + layout.group_text_offset
                )
        img.paste_transparency(
            (await self.fetch("file:assets/bg_subskill.png")).resize(layout.skill_size),
            layout.skill_offset
        )
        img.paste_transparency(
            (await self.fetch("file:assets/text_subskill.png")),
            layout.skill_offset + layout.group_text_offset
        )
        for i, sk in enumerate(party["deck"]["pc"]["set_action"]):
            if len(sk) != 0:
                img.text(
                    (
                        layout.skill_offset
                        + layout.skill_text_offset
                        + V(0, layout.skill_text_line_height * i)
                    ).i,
                    sk["name"],
                    fill=self.WHITE,
                    font=self.font[1]
                )
        equipment : str = None
        if party["is_equipment_familiar"]:
            equipment = f"assets_en/img/sp/assets/familiar/s/{party["deck"]["pc"]["familiar_id"]}.jpg"
        elif party["is_equipment_shield"]:
            equipment = f"assets_en/img/sp/assets/shield/s/{party["deck"]["pc"]["shield_id"]}.jpg"
        if equipment is not None:
            img.paste(
                (await self.fetch(equipment)).resize(layout.equipment_size),
                layout.equipment_offset
            )

    async def draw_individual_summon(
        self : Mizatube,
        img : IMG, folder : str, summon_data : dict,
        position : V, size : V, layout : LayoutSummon
    ) -> bool:
        if summon_data["param"] is None:
            if folder == "s":
                img.paste(
                    (await self.fetch("assets_en/img/sp/tower/assets/npc/s/3999999999.jpg")).resize(size),
                    position
                )
            else:
                img.paste(
                    (await self.fetch("file:assets/open_weapon.png")).resize(size),
                    position
                )
            return False
        else:
            img.paste(
                (await self.fetch(f"assets_en/img/sp/assets/summon/{folder}/{summon_data["param"]["image_id"]}.jpg")).resize(size),
                position
            )
            if summon_data["param"].get("quality", "0") != "0":
                img.text(
                    position + size + layout.plus_offset,
                    f"+{summon_data["param"]["quality"]}",
                    fill=self.PLUS_COLOR,
                    font=self.font[2],
                    stroke_width=6,
                    stroke_fill=self.BLACK
                )
            return True

    async def draw_summon(self : Mizatube, img : IMG, party : dict) -> None:
        # Select layout
        layout : LayoutSummon = LayoutSummon()
        # Draw background
        img.paste_transparency(
            (await self.fetch("file:assets/bg_2.png")).ninepatch(layout.bg_size, layout.bg_margin),
            layout.origin
        )
        for i in range(1, 6):
            summon_data : dict = party["deck"]["pc"]["summons"][str(i)]
            position : V
            folder : str
            if i == 1:
                position = layout.main_position
                size = layout.main_size
                folder = "s"
            else:
                position = (
                    layout.sub_position
                    + V(
                        ((i - 2) % 2) * layout.sub_offset.x,
                        ((i - 2) // 2) * layout.sub_offset.y
                    )
                )
                size = layout.sub_size
                folder = "m"
            if await self.draw_individual_summon(img, folder, summon_data, position, size, layout):
                if summon_data["param"]["id"] == str(party["deck"]["pc"]["quick_user_summon_id"]):
                    img.paste_transparency(
                        (await self.fetch("file:assets/quick.png")).resize(layout.quick_size),
                        position + layout.quick_offset
                    )
        for i in range(1, 3):
            summon_data : dict = party["deck"]["pc"]["sub_summons"][str(i)]
            position = (
                layout.extra_position
                + V(
                    0,
                    (i - 1) * layout.extra_offset.y
                )
            )
            await self.draw_individual_summon(img, "m", summon_data, position, size, layout)
        if party["support_summon"] is not None:
            await self.draw_individual_summon(img, "s", {"param":{"image_id":party["support_summon"]}}, layout.support_position, layout.support_size, layout)
        else:
            await self.draw_individual_summon(img, "s", {"param":None}, layout.support_position, layout.support_size, layout)

    def overwrite_weapon_skill(self : Mizatube, weapon_data : dict) -> None:
        for i in range(3):
            key : str = f"skill{i + 1}"
            if weapon_data[key] is not None:
                sk_name : str = weapon_data[key]["name"]
                match sk_name:
                    case "Cunning Temptation"|"狡知の誘惑": # temptation chain
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14014.jpg"
                    case "Forbidden Fruit"|"禁忌の果実": # forbiddance chain
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14015.jpg"
                    case "Wicked Conduct"|"邪悪と罪": # depravity chain
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14016.jpg"
                    case "Deceitful Fallacy"|"虚偽と詐術": # falsehood chain
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14017.jpg"
                    case "Fulgor Fortis"|"フルゴル・フォルティス": # gauph ena
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/17001.jpg"
                    case "Fulgor Sanatio"|"フルゴル・サーナーティオ": # gauph dio
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/17002.jpg"
                    case "Fulgor Impetus"|"フルゴル・インペトゥス": # gauph tria
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/17003.jpg"
                    case "Fulgor Elatio"|"フルゴル・エーラーティオ": # gauph tessera
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/17004.jpg"
                    case "Strife's Godstrike I"|"Strife's Godstrike II"|"闘争の神撃I"|"闘争の神撃II": # oblivion anklet
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/19001.jpg"
                    case "Strife's Godflair I"|"Strife's Godflair II"|"闘争の神技I"|"闘争の神技II": # ascendance anklet
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/19002.jpg"
                    case "Strife's Godheart I"|"Strife's Godheart II"|"闘争の神奥I"|"闘争の神奥II": # maximality anklet
                        weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/19003.jpg"
                    case _:
                        if sk_name.endswith(("Progression III", "の進境")): # progression chain
                            weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14004.jpg"
                        elif sk_name.endswith(("Ruination", "の極破")): # extremity pendulum
                            weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14005.jpg"
                        elif sk_name.endswith(("Honing", "の極技")): # sagacity pendulum
                            weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14006.jpg"
                        elif sk_name.endswith(("Fathoms", "の極奥")): # supremacy pendulum
                            weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/14007.jpg"
                        elif sk_name.endswith(("Magnitude", "の威烈")): # oblivion teluma
                            weapon_data[key]["overwrite_image"] = "assets_en/img/sp/assets/item/skillplus/s/15009.jpg"

    async def draw_weapon(self : Mizatube, img : IMG, party : dict) -> None:
        # Select layout
        layout : LayoutWeapon
        if self.extra_grid:
            layout = LayoutWeaponExtra()
        else:
            layout = LayoutWeapon()
        # Draw background
        img.paste_transparency(
            (await self.fetch("file:assets/bg_1.png")).resize(layout.bg_size),
            layout.origin
        )
        # Draw boxes
        # # Main
        img.paste(
            (await self.fetch("file:assets/box.png")).ninepatch(layout.main_size + V(0, layout.skill_size.y * 2) + layout.box_margin * 2, layout.box_margin),
            layout.main_position - layout.box_margin
        )
        # # Subs
        img.paste(
            (await self.fetch("file:assets/box.png")).ninepatch(layout.sub_size + layout.sub_offset * 2 + layout.box_margin * 2 + V(0, layout.skill_size.y * 2), layout.box_margin),
            layout.sub_position - layout.box_margin
        )
        # # Extra
        if self.extra_grid:
            img.paste(
                (await self.fetch("file:assets/box_cyan.png")).ninepatch(V(layout.sub_size.x, layout.sub_offset.y * 3) + layout.box_margin * 2, layout.box_margin),
                layout.sub_position + V(3 * layout.sub_offset.x, 0) - layout.box_margin
            )
        # Draw weapons
        for i in range(1, layout.max_weapon + 1):
            if str(i) not in party["deck"]["pc"]["weapons"]:
                weapon_data = {"param":None, "closed":True}
            else:
                weapon_data = party["deck"]["pc"]["weapons"][str(i)]
            position : V
            folder : str
            if i == 1:
                position = layout.main_position
                size = layout.main_size
                folder = "ls"
            else:
                if i > 10:
                    position = (
                        layout.sub_position
                        + V(
                            3 * layout.sub_offset.x,
                            (i - 11) * layout.sub_offset.y
                        )
                    )
                else:
                    position = (
                        layout.sub_position
                        + V(
                            ((i - 2) % 3) * layout.sub_offset.x,
                            ((i - 2) // 3) * layout.sub_offset.y
                        )
                    )
                size = layout.sub_size
                folder = "m"
            if weapon_data["param"] is None:
                if weapon_data.get("closed", False):
                    img.paste(
                        (await self.fetch("file:assets/closed_extra.png")).resize(size),
                        position
                    )
                elif i > 10:
                    img.paste(
                        (await self.fetch("file:assets/open_extra.png")).resize(size),
                        position
                    )
                else:
                    img.paste(
                        (await self.fetch("file:assets/open_weapon.png")).resize(size),
                        position
                    )
                continue
            img.paste(
                (await self.fetch(f"assets_en/img/sp/assets/weapon/{folder}/{weapon_data["param"]["image_id"]}.jpg")).resize(size),
                position
            )
            # Plus marks
            if weapon_data["param"]["quality"] != "0":
                img.text(
                    position + size + layout.plus_offset,
                    f"+{weapon_data["param"]["quality"]}",
                    fill=self.PLUS_COLOR,
                    font=self.font[2],
                    stroke_width=6,
                    stroke_fill=self.BLACK
                )
            skill_lines : int = 0
            if weapon_data["param"]["arousal"]["is_arousal_weapon"]:
                # Awakening
                img.paste_transparency(
                    (await self.fetch(f"assets_en/img/sp/ui/icon/arousal_type/type_{weapon_data["param"]["arousal"]["form"]}.png")).resize(layout.awakening_size),
                    position
                )
                skill_lines = 1
            elif len(weapon_data["param"]["augment_image"]) > 0:
                # AX / Befoulment
                img.paste_transparency(
                    (await self.fetch(f"assets_en/img/sp/ui/icon/augment_skill/{weapon_data["param"]["augment_image"][0]}.png")).resize(layout.awakening_size),
                    position
                )
                skill_lines = 1
            # Skills
            has_skill : bool = False
            for i in range(3):
                if weapon_data[f"skill{i + 1}"] is not None:
                    has_skill = True
                    skill_lines += 1
                    break
            if skill_lines > 0:
                img.paste_transparency(
                    (await self.fetch("file:assets/bg_skill.png")).resize(V(size.x, layout.skill_size.y * skill_lines)),
                    position + V(0, size.y)
                )
                if has_skill:
                    if weapon_data["param"]["skill_level"] != "1":
                        img.text(
                            position + V(0, size.y) + V(layout.skill_size.x, 0) * 2 + layout.skill_text_offset,
                            f"Lv {weapon_data["param"]["skill_level"]}",
                            fill=self.WHITE,
                            font=self.font[2]
                        )
                    self.overwrite_weapon_skill(weapon_data)
                    for i in range(3):
                        key : str = f"skill{i + 1}"
                        if weapon_data[key] is not None:
                            if "overwrite_image" in weapon_data[key]:
                                img.paste(
                                    (await self.fetch(weapon_data[key]["overwrite_image"])).resize(layout.skill_size),
                                    position + V(0, size.y) + V(layout.skill_size.x, 0) * i
                                )
                            else:
                                img.paste(
                                    (await self.fetch(f"assets_en/img/sp/ui/icon/skill/{weapon_data[key]["image"]}.png")).resize(layout.skill_size),
                                    position + V(0, size.y) + V(layout.skill_size.x, 0) * i
                                )
                    skill_lines -= 1
                if weapon_data["param"]["arousal"]["is_arousal_weapon"]:
                    img.paste_transparency(
                        (await self.fetch(f"assets_en/img/sp/ui/icon/arousal_type/type_{weapon_data["param"]["arousal"]["form"]}.png")).resize(layout.skill_size),
                        position + V(0, size.y) + V(0, layout.skill_size.y) * skill_lines
                    )
                    img.text(
                        position + V(0, size.y) + V(0, layout.skill_size.y) * skill_lines + V(layout.skill_size.x, 0) + layout.skill_text_offset,
                        f"Lv {weapon_data["param"]["arousal"]["level"]}",
                        fill=self.WHITE,
                        font=self.font[2]
                    )
                elif len(weapon_data["param"]["augment_image"]) > 0:
                    for i in range(min(2, len(weapon_data["param"]["augment_skill_icon_image"]))):
                        img.paste_transparency(
                            (await self.fetch(f"assets_en/img/sp/ui/icon/skill/{weapon_data["param"]["augment_skill_icon_image"][i]}.png")).resize(layout.skill_size),
                            position + V(0, size.y) + V(0, layout.skill_size.y) * skill_lines + V(layout.skill_size.x + layout.skill_spacer, 0) * i
                        )
                        img.text(
                            position + V(0, size.y) + V(0, layout.skill_size.y) * skill_lines + V(layout.skill_size.x, 0) + V(layout.skill_size.x + layout.skill_spacer, 0) * i + layout.skill_text_offset,
                            weapon_data["param"]["augment_skill_info"][0][i]["show_value"].replace("+", "").replace("%", ""),
                            fill=self.WHITE,
                            font=self.font[2]
                        )

    async def draw_estimate(self : Mizatube, img : IMG, party : dict) -> None:
        # Select layout
        layout : LayoutEstimate = LayoutEstimate()
        # Draw background
        img.paste_transparency(
            (await self.fetch("file:assets/bg_2.png")).ninepatch(layout.bg_size, layout.bg_margin),
            layout.origin
        )
        damage_info = party["deck"]["pc"]["damage_info"]
        # Draw stats
        for i in range(2):
            img.paste_transparency(
                (await self.fetch("file:assets/bg_text.png")).ninepatch(layout.stat_size, 1),
                layout.stat_offset + V(0, layout.stat_size.y) * i
            )
            img.paste_transparency(
                (await self.fetch("file:assets/" + ("atk" if i == 0 else "hp") + ".png")),
                layout.stat_offset + V(0, layout.stat_size.y) * i + layout.stat_text_icon_offset
            )
            img.text(
                layout.stat_offset + V(0, layout.stat_size.y) * i + layout.stat_text_offset,
                str(party["deck"]["pc"]["param"]["attack" if i == 0 else "hp"]),
                fill=self.WHITE,
                font=self.font[3]
            )
            img.paste_transparency(
                (await self.fetch("file:assets/bg_stat.png")).ninepatch(layout.estimate_size, 30),
                layout.estimate_offset[i]
            )
            img.text(
                layout.estimate_offset[i] + layout.estimate_text_offset,
                str(damage_info["assumed_normal_damage" if i == 0 else "assumed_advantage_damage"]),
                fill=self.COLORS[damage_info["assumed_normal_damage_attribute"]],
                font=self.font[3]
            )
            if i == 0:
                img.text(
                    layout.estimate_offset[i] + layout.estimate_sub_text_offset,
                    "Estimated",
                    fill=self.WHITE,
                    font=self.font[2]
                )
            else:
                img.text(
                    layout.estimate_offset[i] + layout.estimate_sub_text_offset,
                    "vs",
                    fill=self.WHITE,
                    font=self.font[2]
                )
                vs_color_index : int
                if damage_info["assumed_normal_damage_attribute"] <= 4:
                    vs_color_index = (damage_info["assumed_normal_damage_attribute"] + 2) % 4 + 1
                else:
                    vs_color_index = (damage_info["assumed_normal_damage_attribute"] - 5 + 1) % 2 + 5
                img.text(
                    layout.estimate_offset[i] + layout.estimate_sub_text_offset + layout.vs_offset,
                    self.COLORS_TXT[vs_color_index],
                    fill=self.COLORS[vs_color_index],
                    font=self.font[2]
                )
        # HP bar
        hp_ratio = int(party["calculator"][1]) / 100.0
        img.paste(
            (await self.fetch("file:assets/hp_bottom.png")).ninepatch(layout.hp_bar_size, 3),
            layout.hp_bar_offset
        )
        img.paste_transparency(
            (await self.fetch("file:assets/hp_mid.png")).ninepatch(layout.hp_bar_size, 3).crop((layout.hp_bar_size.x * hp_ratio, layout.hp_bar_size.y)),
            layout.hp_bar_offset
        )
        img.paste_transparency(
            (await self.fetch("file:assets/hp_top.png")).ninepatch(layout.hp_bar_size, 3),
            layout.hp_bar_offset
        )
        img.text(
            layout.hp_bar_offset + V(0, layout.hp_bar_size.y + 5),
            f"HP {party["calculator"][1]}%",
            fill=self.WHITE,
            font=self.font[1],
            stroke_width=2,
            stroke_fill=self.BLACK
        )
        # Boosts
        position : V = layout.boost_origin
        BOOSTS : dict[str, str] = {
            "weapon_skill_enhance":"icon_skillenhance_1",
            "weapon_skill_enhance_magna":"icon_skillenhance_2",
            "weapon_skill_enhance_evil":"icon_skillenhance_3"
        }
        for k, v in BOOSTS.items():
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/ui/icon/weapon_skill_enhance/{v}.png")).resize(layout.boost_size),
                position
            )
            img.text(
                position + layout.boost_text_offset,
                f"{damage_info["weapon_skill_enhance_param"][k]}%",
                fill=(self.COLORS[damage_info["assumed_normal_damage_attribute"]] if damage_info["weapon_skill_enhance_param"][k] >= 280 else self.WHITE),
                font=self.font[2],
                stroke_width=2,
                stroke_fill=self.BLACK
            )
            position += V(layout.boost_horizontal_offset, 0)

    async def draw_modifiers(self : Mizatube, img : IMG, party : dict) -> None:
        # Select layout
        layout : LayoutModifier = LayoutModifier()
        # Draw background
        bg_h : int = (len(party["deck"]["pc"]["damage_info"]["effect_value_info"]) // 6 + 1) * layout.mod_vertical_offset + layout.bg_margin * 5
        img.paste_transparency(
            (await self.fetch("file:assets/bg_1.png")).ninepatch(V(IMAGE_SIZE.x, bg_h), layout.bg_margin),
            layout.origin
        )
        position : V = layout.mod_offset_start
        for i, mod in enumerate(party["deck"]["pc"]["damage_info"]["effect_value_info"]):
            if i > 0:
                if i % layout.mod_per_line == 0:
                    position += V(0, layout.mod_vertical_offset)
                    position.x = layout.mod_offset_start.x
                else:
                    position += V(layout.mod_horizontal_offset, 0)
            img.paste_transparency(
                await self.fetch(f"assets_en/img/sp/ui/icon/weapon_skill_label/{mod["icon_img"]}"),
                position
            )
            img.paste(
                (await self.fetch("file:assets/box.png")).resize(layout.mod_box),
                position + V(0, layout.mod_size.y + 1)
            )
            img.text(
                position + layout.mod_text_offset,
                str(mod['value']),
                fill=(self.MODIFIER_MAX_COLOR if mod['is_max'] else self.WHITE),
                font=self.font[2]
            )

    def shorten_emp_name(self : Mizatube, base : str) -> str:
        match base:
            case "Debuff Success Rate":
                return "Debuff"
            case "Skill DMG Cap":
                return "Sk. Cap"
            case "C.A. DMG Cap":
                return "C.A. Cap"
            case "Critical Hit Rate":
                return "Crit."
            case "Enmity":
                return "Enmi."
            case "Stamina":
                return "Stam."
            case "Healing":
                return "Heal."
            case "Debuff Resistance":
                return "D. Res."
            case "Dodge Rate":
                return "Dodge"
            case "Double Attack Rate":
                return "D.A."
            case "Triple Attack Rate":
                return "T.A."
            case "Fire ATK"|"Water ATK"|"Earth ATK"|"Wind ATK"|"Light ATK"|"Dark ATK":
                return "ATK"
            case "Fire Resistance"|"Water Resistance"|"Earth Resistance"|"Wind Resistance"|"Light Resistance"|"Dark Resistance":
                return "Res."
            case "Supplemental DMG":
                return "Supp."
            case "Counters on Dodge":
                return "Ct. Dodge"
            case "Counters on DMG":
                return "Ct. DMG"
            case _:
                return base

    async def draw_individual_emp(
        self : Mizatube,
        img : IMG, layout : LayoutEMP,
        position : V, chara_data : dict,
        emp_data : dict, party : dict
    ) -> None:
        img.paste_transparency(
            (await self.fetch("file:assets/bg_1.png")).ninepatch(layout.size, layout.margin),
            position
        )
        chara_file : str
        chara_file, _ = self.find_chara_file(
            chara_data["master"]["id"],
            chara_data["param"]["level"],
            chara_data["param"]["evolution"],
            chara_data["param"]["style"],
            party["deck"]["pc"]["param"]["attribute"]
        )
        # Portrait
        try:
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/assets/npc/{layout.portrait_folder}/{chara_file}.jpg")).resize(layout.portrait_size),
                position + layout.portrait_offset
            )
        except:
            # Try png if it fails
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/assets/npc/{layout.portrait_folder}/{chara_file}.png")).resize(layout.portrait_size),
                position + layout.portrait_offset
            )
        # Awakening
        if chara_data["param"]["npc_arousal_form"] is not None:
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/ui/icon/npc_arousal_form/form_{chara_data["param"]["npc_arousal_form"]}.png")).resize(layout.arousal_icon_size),
                position + layout.arousal_icon_offset
            )
        # Ring
        if chara_data["param"]["has_npcaugment_constant"]:
            img.paste_transparency(
                (await self.fetch("assets_en/img/sp/ui/icon/augment2/icon_augment2_l.png")).resize(layout.ring_size),
                position + layout.ring_offset
            )
        # EMP
        emp_position : V = position + layout.emp_start_offset
        emp_display : int = 1 if len(emp_data['emp']) > 15 else 0
        for i, emp in enumerate(emp_data['emp']):
            if i > 0:
                if i % layout.emp_per_line[emp_display] == 0:
                    emp_position.x = position.x + layout.emp_start_offset.x
                    emp_position.y += layout.emp_size[emp_display].y
                else:
                    emp_position.x += layout.emp_size[emp_display].x
            if emp.get('is_lock', False):
                img.paste(
                    (await self.fetch("assets_en/img/sp/zenith/assets/ability/lock.png")).resize(layout.emp_size[emp_display]),
                    emp_position
                )
            else:
                img.paste(
                    (await self.fetch(f"assets_en/img/sp/zenith/assets/ability/{emp['image']}.png")).resize(layout.emp_size[emp_display]),
                    emp_position
                )
                if str(emp['current_level']) != "0":
                    img.text(
                        emp_position + layout.emp_count_offset,
                        str(emp['current_level']),
                        fill=(235, 227, 250),
                        font=self.font[layout.emp_count_font],
                        stroke_width=5,
                        stroke_fill=self.BLACK
                    )
                else:
                    img.paste_transparency(
                        (await self.fetch("file:assets/emp_unused.png")).resize(layout.emp_size[emp_display]),
                        emp_position
                    )
        # Extra
        emp_position = position + layout.extra_start_offset
        for i, ring in enumerate(emp_data['ring']):
            if i > 0:
                if i % layout.extra_per_line == 0:
                    emp_position.x = position.x + layout.extra_start_offset.x
                    emp_position.y += layout.extra_line_jump
                else:
                    emp_position += layout.extra_offset
            img.paste_transparency(
                (await self.fetch(f"file:assets/{ring['type']['image']}.png")).resize(layout.extra_icon_size),
                emp_position
            )
            match layout.extra_compact_mode:
                case 1:
                    emp_name : str = self.shorten_emp_name(ring['type']['name'])
                    img.text(
                        emp_position + layout.extra_text_offset,
                        emp_name + " " + ring['param']['disp_total_param'],
                        fill=self.PLUS_COLOR,
                        font=self.font[1],
                        stroke_width=3,
                        stroke_fill=self.BLACK
                    )
                case 2:
                    img.text(
                        emp_position + layout.extra_text_offset,
                        ring['param']['disp_total_param'],
                        fill=self.PLUS_COLOR,
                        font=self.font[0],
                        stroke_width=3,
                        stroke_fill=self.BLACK
                    )
                case _:
                    img.text(
                        emp_position + layout.extra_text_offset,
                        ring['type']['name'] + " " + ring['param']['disp_total_param'],
                        fill=self.PLUS_COLOR,
                        font=self.font[1],
                        stroke_width=3,
                        stroke_fill=self.BLACK
                    )
        # Domain/Radiance/Etc...
        for key in ['domain', 'saint', 'extra']:
            if key in emp_data and len(emp_data[key]) > 0:
                extra_txt : str = ""
                # set txt, icon and color according to specifics
                icon_path : str
                text_color : tuple[int, int, int]
                match key:
                    case 'domain':
                        icon_path = "assets_en/img/sp/ui/icon/ability/m/1426_3.png"
                        text_color = self.DOMAIN_COLOR
                        lv = 0
                        for el in emp_data[key]:
                            if el[2] is not None: lv += 1
                        extra_txt = "Lv" + str(lv)
                    case 'extra':
                        icon_path = "assets_en/img/sp/ui/icon/ability/m/2487_3.png"
                        text_color = self.RADIANCE_COLOR
                        extra_txt = "Lv" + str(len(emp_data[key]))
                    case 'saint':
                        icon_path = "assets_en/img/sp/ui/icon/skill/skill_job_weapon.png"
                        text_color = self.SAINT_COLOR
                        lv = [0, 0]
                        for el in emp_data[key]:
                            if el[0].startswith("ico-progress-gauge"):
                                if el[0].endswith(" on"):
                                    lv[0] += 1
                                lv[1] += 1
                        extra_txt = "{}/{}".format(lv[0], lv[1])
                    case _:
                        icon_path = "assets_en/img/sp/ui/icon/skill/skill_job_weapon.png"
                        text_color = self.SAINT_COLOR
                        extra_txt = "Lv" + str(len(emp_data[key]))
                # add to image
                img.paste_transparency(
                    (await self.fetch(icon_path)).resize(layout.domain_size),
                    position + layout.domain_offset
                )
                img.text(
                    position + layout.domain_offset + layout.domain_text_offset,
                    extra_txt,
                    fill=text_color,
                    font=self.font[1],
                    stroke_width=3,
                    stroke_fill=self.BLACK
                )

    def shorten_artifact_text(self : Mizatube, text : str, limit : int) -> str:
        if len(text) > limit:
            return text[:limit-1].strip() + "..."
        return text

    async def draw_individual_artifact(
        self : Mizatube,
        img : IMG, layout : LayoutArtifact,
        position : V, chara_data : dict,
        artifact_data : dict, party : dict
    ) -> None:
        img.paste_transparency(
            (await self.fetch("file:assets/bg_1.png")).ninepatch(layout.size, layout.margin),
            position
        )
        chara_file : str
        chara_file, _ = self.find_chara_file(
            chara_data["master"]["id"],
            chara_data["param"]["level"],
            chara_data["param"]["evolution"],
            chara_data["param"]["style"],
            party["deck"]["pc"]["param"]["attribute"]
        )
        # Portrait
        try:
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/assets/npc/{layout.portrait_folder}/{chara_file}.jpg")).resize(layout.portrait_size),
                position + layout.portrait_offset
            )
        except:
            # Try png if it fails
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/assets/npc/{layout.portrait_folder}/{chara_file}.png")).resize(layout.portrait_size),
                position + layout.portrait_offset
            )
        # Awakening
        if chara_data["param"]["npc_arousal_form"] is not None:
            img.paste_transparency(
                (await self.fetch(f"assets_en/img/sp/ui/icon/npc_arousal_form/form_{chara_data["param"]["npc_arousal_form"]}.png")).resize(layout.arousal_icon_size),
                position + layout.arousal_icon_offset
            )
        # Ring
        if chara_data["param"]["has_npcaugment_constant"]:
            img.paste_transparency(
                (await self.fetch("assets_en/img/sp/ui/icon/augment2/icon_augment2_l.png")).resize(layout.ring_size),
                position + layout.ring_offset
            )
        # Artifact
        skill_position = position + layout.skill_start_offset
        for i, skill in enumerate(artifact_data['artifact']['skills']):
            if i > 0:
                if i % layout.skill_per_line == 0 or (i == 3 and layout.skill_compact_mode == 1):
                    skill_position.x = position.x + layout.skill_start_offset.x
                    skill_position.y += layout.skill_line_jump
                else:
                    skill_position += layout.skill_offset
            icon : str = ( # compatibility with older formats
                skill['icon'] 
                if skill['icon'].startswith('assets')
                else f"assets_en/img/sp/ui/icon/bonus/{skill['icon']}"
            )
            img.paste_transparency(
                (await self.fetch(icon)).resize(layout.skill_icon_size),
                skill_position
            )
            img.text(
                skill_position + layout.skill_text_offset,
                "Lv " + skill['lvl'],
                fill=self.WHITE,
                font=self.font[1],
                stroke_width=3,
                stroke_fill=self.BLACK
            )
            img.text(
                skill_position + layout.skill_value_offset,
                skill['value'].split(" ", 1)[0],
                fill=self.PLUS_COLOR,
                font=self.font[1],
                stroke_width=3,
                stroke_fill=self.BLACK
            )
            chara_limit : int = layout.skill_desc_chara_limit
            if layout.skill_compact_mode == 1:
                if i < 2:
                    chara_limit = layout.skill_desc_chara_limit_compact
            elif layout.skill_compact_mode == 2:
                chara_limit = layout.skill_desc_chara_limit_compact
            img.text(
                skill_position + layout.skill_desc_offset,
                self.shorten_artifact_text(skill['desc'], chara_limit),
                fill=self.WHITE,
                font=self.font[1],
                stroke_width=3,
                stroke_fill=self.BLACK
            )

    async def make_page1(self : Mizatube, img : IMG, party : dict) -> tuple[bool, Any]:
        try:
            await self.draw_summon(img, party)
            await self.draw_weapon(img, party)
            img.save("output_page1.png", self.args["dry"])
            return (True, None)
        except Exception as e:
            return (False, e)

    async def make_page2(self : Mizatube, img : IMG, party : dict) -> tuple[bool, Any]:
        try:
            await self.draw_estimate(img, party)
            await self.draw_modifiers(img, party)
            img.save("output_page2.png", self.args["dry"])
            return (True, None)
        except Exception as e:
            return (False, e)

    async def make_emp(self : Mizatube, party : dict) -> tuple[bool, Any]:
        try:
            img : IMG = IMG.new_canvas()
            emps : dict = {}
            for k, v in party["deck"]["npc"].items():
                try:
                    emps[k] = self.load_emp(v["master"]["id"])
                except:
                    pass
            n_chara : int = len(emps.keys())
            layout : LayoutEMP
            if n_chara <= 5:
                layout = LayoutEMP()
            elif n_chara <= 8:
                layout = LayoutEMPCompact()
            else:
                layout = LayoutEMPVeryCompact()
            position : V = layout.origin
            for k, emp_data in emps.items():
                await self.draw_individual_emp(img, layout, position, party["deck"]["npc"][k], emp_data, party)
                position += layout.offset
            img.save("output_emp.png", self.args["dry"])
            return (True, None)
        except Exception as e:
            return (False, e)

    async def make_artifact(self : Mizatube, party : dict) -> tuple[bool, Any]:
        try:
            img : IMG = IMG.new_canvas()
            artifacts : dict = {}
            for k, v in party["deck"]["npc"].items():
                try:
                    artifact_data = self.load_artifact(v["master"]["id"])
                    if "skills" not in artifact_data["artifact"]:
                        continue
                    artifacts[k] = artifact_data
                except:
                    pass
            n_chara : int = len(artifacts.keys())
            layout : LayoutArtifact
            if n_chara <= 5:
                layout = LayoutArtifact()
            elif n_chara <= 8:
                layout = LayoutArtifactCompact()
            else:
                layout = LayoutArtifactVeryCompact()
            position : V = layout.origin
            for k, artifact_data in artifacts.items():
                await self.draw_individual_artifact(img, layout, position, party["deck"]["npc"][k], artifact_data, party)
                position += layout.offset
            img.save("output_artifact.png", self.args["dry"])
            return (True, None)
        except Exception as e:
            return (False, e)

    async def process_party(self : Mizatube, data : dict) -> bool:
        folder : Path = Path("cache")
        if not folder.exists():
            folder.mkdir()
        print("Generating images...")
        # load language fonts
        if self.language != data["lang"] or self.font is None:
            self.language = data["lang"]
            self.load_fonts()
        # set flags
        self.extra_grid = len(data["party"]["deck"]["pc"]["weapons"]) > 10
        self.extra_summon = len(data["party"]["deck"]["pc"].get("sub_summons", {})) > 0
        # start image generation
        start : float = time.time()
        tasks : list[asyncio.Task] = []
        async with asyncio.TaskGroup() as tg:
            tasks.append(tg.create_task(self.make_emp(data["party"])))
            tasks.append(tg.create_task(self.make_artifact(data["party"])))
            # Top party is used on 2 pages, so we generate it first here
            img : IMG = IMG.new_canvas()
            await self.draw_party(img, data["party"])
            tasks.append(tg.create_task(self.make_page1(img, data["party"])))
            tasks.append(tg.create_task(self.make_page2(img.copy(), data["party"])))
        end : float = time.time()
        for t in tasks:
            result, exception = t.result()
            if not result:
                print(pexc(exception))
                print("Process has been stopped")
                return False
        print(f"Images generated in {end - start:.2f} seconds")
        return True

    async def run(self : Mizatube) -> None:
        try:
            if self.args.get("json", None) is not None:
                with open(self.args["json"], mode="r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = read_clipboard()
        except Exception as e:
            print(pexc(e))
            print("An error occured")
            print("Did you click the bookmark?")
            return
        ver : int = data.get('ver', 0)
        if ver < self.BOOKMARK_VERSION:
            print("Error: Your bookmark is outdated, please update it!")
            return
        elif ver > self.BOOKMARK_VERSION:
            print("Warning: Your bookmark is from a newer version, please consider updating the script.")
        try:
            if "emp" in data:
                self.process_emp(data)
            elif "artifact" in data:
                self.process_artifact(data)
            elif "party" in data:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as self.client:
                    if self.args.get("skipparty", False):
                        if not self.args.get("nothumbnail", False):
                            await self.process_thumbnail(data)
                    else:
                    
                        if (
                            await self.process_party(data)
                            and not self.args.get("nothumbnail", False)
                            and self.input("Type 'y' and press return to make a thumbnail:").lower() == "y"
                        ):
                            await self.process_thumbnail(data)
            elif "id" in data:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as self.client:
                    data.pop("ver", None)
                    img : IMG|None = await self.make_boss_background(data)
                    if img is None:
                        print("Error: Couldn't generate a thumbnail from this boss data.")
                    else:
                        img.show()
                        self.register_boss(data)
            else:
                print("Error: No compatible data in the clipboard.")
        except Exception as e:
            print(pexc(e))
            print("An unexpected error occured")

    def list_bosses(self : Mizatube) -> None:
        self.load_bosses()
        if len(self.bosses) == 0:
            print("No registered bosses")
        else:
            for k, v in self.bosses.items():
                print(k)

    async def test_boss(self : Mizatube, name : str) -> None:
        self.load_bosses()
        if name not in self.bosses:
            print(name, "not found in the boss data")
            r = self.search_boss(name)
            if len(r) > 0:
                print("Did you mean...?")
                print("*", "\n* ".join(r))
        else:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as self.client:
                img : IMG|None = await self.make_boss_background(self.bosses[name])
                if img is None:
                    print("Error: Couldn't generate a thumbnail from this boss data.")
                else:
                    img.show()

    def clear_cache(self : Mizatube) -> None:
        folder : Path = Path("cache")
        if folder.exists() and folder.is_dir():
            shutil.rmtree(folder)
            self.tasks.print("Cache folder cleared.")

    async def start(self : Mizatube) -> None:
        # parse parameters
        prog_name : str
        try:
            prog_name = sys.argv[0].replace('\\', '/').split('/')[-1]
        except:
            prog_name = "mizatube.py" # fallback to default
        # Set Argument Parser
        parser : argparse.ArgumentParser = argparse.ArgumentParser(prog=prog_name, description=f"Mizako's Youtube script v{self.VERSION}")
        primary = parser.add_argument_group('primary', 'main commands.')
        primary.add_argument('-j', '--json', help="pass party data as a json file path", action='store', nargs=1, type=str, metavar='PATH')
        primary.add_argument('-i', '--input', help="set text inputs", nargs='+', default=None)
        primary.add_argument('-nt', '--nothumbnail', help="disable thumbnail prompt", action='store_const', const=True, default=False, metavar='')
        primary.add_argument('-sp', '--skipparty', help="skip party image generation to make only a thumbnail", action='store_const', const=True, default=False, metavar='')
        
        utility = parser.add_argument_group('utility', 'utility commands.')
        utility.add_argument('-dr', '--dryrun', help="images won't be written (for debugging)", action='store_const', const=True, default=False, metavar='')
        utility.add_argument('-lb', '--listbosses', help="list registered bosses", action='store_const', const=True, default=False, metavar='')
        utility.add_argument('-tb', '--testboss', help="generate a boss image as a test", action='store', nargs=1, type=str, metavar='PATH')
        utility.add_argument('-cc', '--clearcache', help="clear the cache folder", action='store_const', const=True, default=False, metavar='')
        utility.add_argument('-ex', '--exit', help="exit after parsing the arguments, without running the script", action='store_const', const=True, default=False, metavar='')
        args : argparse.Namespace = parser.parse_args()
        self.args = {
            "dry":args.dryrun,
            "nothumbnail":args.nothumbnail,
            "skipparty":args.skipparty
        }
        if args.json is not None:
            self.args["json"] = args.json[0]
        if args.clearcache:
            self.clear_cache()
        if args.listbosses:
            self.list_bosses()
        if args.testboss is not None:
            await self.test_boss(args.testboss[0])
        if args.exit:
            return
        if args.input is not None and len(args.input) > 0:
            self.args["input"] = args.input
        await self.run()

if __name__ == "__main__":
    asyncio.run(Mizatube().start())