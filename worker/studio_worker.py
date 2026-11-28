#!/usr/bin/env python3
"""AI OFFICE V5.0 STUDIO — 제작 워커 (Phase 1).

하는 일
  studio_jobs 큐에서 render_card / render_thumb / encode_video / make_subs / audio_check 잡을 선점해
  Chromium(Playwright) 렌더 · FFmpeg 인코딩/자막/음량 분석을 수행하고 결과 파일을 Supabase Storage
  (studio-assets, 비공개)에 올린 뒤 studio_assets 에 등록하고 job 을 완료 처리한다.

실행 위치
  - GitHub Actions 워커(권장, 0원): .github/workflows/studio-worker.yml
  - 수동/복구: python3 worker/studio_worker.py --once
  - 상시 루프: python3 worker/studio_worker.py --loop 20

필요 환경변수
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (필수)
  WORKER_NAME(기본 studio-worker) · FFMPEG_BIN(기본 ffmpeg) · NODE_BIN(기본 node)
  CHROMIUM_PATH(선택, Playwright 브라우저 경로)

보안: service_role 키는 이 프로세스 환경에만 있고 산출물·로그에 남기지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(BASE, 'render.mjs')

SUPABASE_URL = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or ''
WORKER = os.environ.get('WORKER_NAME') or 'studio-worker'
NODE = os.environ.get('NODE_BIN') or 'node'
FFMPEG = os.environ.get('FFMPEG_BIN') or 'ffmpeg'
BUCKET = 'studio-assets'

CARD_SIZES = {
    'instagram': (1080, 1350),
    'threads': (1080, 1350),
    'tistory': (1080, 1350),
    'naver': (1080, 1350),
    'youtube': (1920, 1080),
}


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _headers(extra: dict | None = None) -> dict:
    head = {'apikey': SERVICE_KEY, 'Authorization': 'Bearer ' + SERVICE_KEY, 'Content-Type': 'application/json'}
    if extra:
        head.update(extra)
    return head


def rest(path: str, method: str = 'GET', body: dict | None = None, prefer: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    extra = {'Prefer': prefer} if prefer else None
    req = urllib.request.Request(
        f'{SUPABASE_URL}/rest/v1/{path}', data=data, method=method, headers=_headers(extra)
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            raw = res.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as err:
        body = err.read()[:400].decode('utf-8', 'ignore')
        raise RuntimeError(f'{method} {path} -> {err.code}: {body}') from err


def rpc(name: str, body: dict):
    return rest(f'rpc/{name}', method='POST', body=body)


def upload(path: str, blob: bytes, mime: str) -> str:
    req = urllib.request.Request(
        f'{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}',
        data=blob,
        method='POST',
        headers={
            'Authorization': 'Bearer ' + SERVICE_KEY,
            'apikey': SERVICE_KEY,
            'Content-Type': mime,
            'x-upsert': 'true',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            if res.status >= 300:
                raise RuntimeError(f'upload failed {res.status}: {(res.read() or b"")[:300]!r}')
    except urllib.error.HTTPError as err:
        body = err.read()[:400].decode('utf-8', 'ignore')
        raise RuntimeError(f'upload HTTP {err.code}: {body}') from err
    return f'{BUCKET}/{path}'


# --------------------------------------------------------------------------- #
# Templates (한국어 카드 · 썸네일)
# --------------------------------------------------------------------------- #
ACCENTS = {
    'youtube': '#ff4d4d',
    'instagram': '#e1306c',
    'threads': '#8b5cf6',
    'tistory': '#ff7a00',
    'naver': '#03c75a',
}
PLATFORM_LABEL = {
    'youtube': 'YOUTUBE', 'instagram': 'INSTAGRAM', 'threads': 'THREADS',
    'tistory': 'TISTORY', 'naver': 'NAVER BLOG',
}


def esc(value: str) -> str:
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def card_html(item: dict, slide: dict, index: int, total: int) -> str:
    platform = item.get('platform', 'instagram')
    accent = ACCENTS.get(platform, '#ffd400')
    plan = item.get('plan') or {}
    heading = esc(slide.get('heading') or item.get('title') or '')
    body = esc(slide.get('body') or '')
    title = esc(item.get('title') or '')
    brand = esc(item.get('brand') or 'AI OFFICE')
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
  @font-face {{ font-family: 'NotoKR'; src: local('Noto Sans CJK KR'), local('Noto Sans KR'); }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: {CARD_SIZES.get(platform, (1080, 1350))[0]}px; height: {CARD_SIZES.get(platform, (1080, 1350))[1]}px;
         font-family: 'NotoKR', 'Noto Sans CJK KR', sans-serif; background: #0e0e12; color: #fff; overflow: hidden; }}
  .card {{ position: relative; width: 100%; height: 100%; padding: 86px 88px 92px; display: flex; flex-direction: column;
           justify-content: space-between;
           background: radial-gradient(1100px 620px at 92% -8%, {accent}33 0%, transparent 62%), #0e0e12; }}
  .top {{ display: flex; justify-content: space-between; align-items: center; font-size: 30px; letter-spacing: 2px; color: #ffffff99; }}
  .badge {{ color: {accent}; font-weight: 700; }}
  .index {{ font-variant-numeric: tabular-nums; }}
  .mid {{ display: flex; flex-direction: column; justify-content: flex-start; flex: 1; margin-top: 110px; padding-right: 8px; }}
  .num {{ font-size: 34px; font-weight: 800; color: {accent}; letter-spacing: 4px; margin-bottom: 26px; }}
  h1 {{ font-size: 78px; line-height: 1.2; font-weight: 800; letter-spacing: -1.2px; }}
  p {{ margin-top: 34px; font-size: 42px; line-height: 1.55; color: #e6e7ee; font-weight: 400; }}
  .bottom {{ display: flex; flex-direction: column; gap: 26px; margin-top: auto; }}
  .rule {{ width: 132px; height: 9px; background: {accent}; border-radius: 6px; }}
  .foot {{ display: flex; justify-content: space-between; font-size: 27px; color: #ffffff80; }}
  .bar {{ position: absolute; left: 0; bottom: 0; height: 10px; width: {int(100 * (index + 1) / max(total, 1))}%; background: {accent}; }}
</style></head><body><div class="card">
  <div class="top"><span class="badge">{PLATFORM_LABEL.get(platform, platform.upper())} · STUDIO</span><span class="index">{index + 1} / {total}</span></div>
  <div class="mid">
    <div class="num">{index + 1:02d}</div>
    <h1>{heading}</h1>
    <p>{body}</p>
  </div>
  <div class="bottom">
    <div class="rule"></div>
    <div class="foot"><span>{title}</span><span>{brand}</span></div>
  </div>
  <div class="bar"></div>
</div></body></html>"""


def thumb_html(item: dict) -> str:
    platform = item.get('platform', 'youtube')
    accent = ACCENTS.get(platform, '#ff4d4d')
    plan = item.get('plan') or {}
    raw_title = item.get('title') or ''
    title = esc(raw_title)
    hook = esc(plan.get('hook') or (item.get('meta') or {}).get('description', '')[:40])
    brand = esc(item.get('brand') or 'AI OFFICE')
    # 제목 길이에 따라 크기를 줄여 한 줄에 최대한 담는다(단어 하나만 남는 줄 방지).
    length = len(raw_title)
    title_size = 92 if length <= 16 else 76 if length <= 22 else 64 if length <= 30 else 54
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: 1280px; height: 720px; font-family: 'Noto Sans CJK KR', sans-serif; background: #111318; color: #fff; overflow: hidden; }}
  .wrap {{ position: relative; width: 100%; height: 100%; padding: 64px 76px; display: flex; flex-direction: column; justify-content: center;
           background: linear-gradient(135deg, {accent}55 0%, transparent 46%), linear-gradient(315deg, #1d2230 0%, #0b0d12 100%); }}
  .kicker {{ font-size: 28px; letter-spacing: 3px; color: {accent}; font-weight: 700; }}
  h1 {{ margin-top: 24px; font-size: {title_size}px; line-height: 1.16; font-weight: 900; letter-spacing: -1.5px; max-width: 1080px; word-break: keep-all; }}
  .hook {{ margin-top: 30px; font-size: 36px; color: #d6d9e3; }}
  .brand {{ position: absolute; right: 76px; bottom: 56px; font-size: 26px; color: #ffffff77; }}
  .time {{ position: absolute; right: 76px; bottom: 100px; font-size: 30px; background: #000000aa; color: #fff; padding: 8px 16px; border-radius: 8px; }}
</style></head><body><div class="wrap">
  <div class="kicker">{PLATFORM_LABEL.get(platform, 'STUDIO')}</div>
  <h1>{title}</h1>
  <div class="hook">{hook}</div>
  <div class="brand">{brand}</div>
</div></body></html>"""


# --------------------------------------------------------------------------- #
# Job handlers
# --------------------------------------------------------------------------- #
def load_item(item_id: str) -> dict:
    rows = rest(f'studio_items?select=*&id=eq.{item_id}&limit=1')
    if not rows:
        raise RuntimeError(f'item not found: {item_id}')
    return rows[0]


def slides_of(item: dict) -> list[dict]:
    plan = item.get('plan') or {}
    slides = plan.get('slides') if isinstance(plan, dict) else None
    if isinstance(slides, list) and slides:
        out = []
        for slide in slides[:8]:
            if isinstance(slide, dict):
                out.append({'heading': str(slide.get('heading') or ''), 'body': str(slide.get('body') or '')})
        if out:
            return out
    return [{'heading': item.get('title') or '콘텐츠', 'body': (item.get('meta') or {}).get('description', '') or ''}]


def render_png(item: dict, html: str, width: int, height: int, out: str, scale: float = 1.0) -> None:
    spec = {'html': html, 'width': width, 'height': height, 'out': out, 'scale': scale}
    spec_path = out + '.spec.json'
    with open(spec_path, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)
    env = dict(os.environ)
    proc = subprocess.run([NODE, RENDER, spec_path], capture_output=True, text=True, timeout=180, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f'render failed: {proc.stderr[-800:]}')
    if not os.path.exists(out):
        raise RuntimeError('render produced no file')


def card_pngs(item: dict, tmp: str) -> list[str]:
    platform = item.get('platform', 'instagram')
    width, height = CARD_SIZES.get(platform, (1080, 1350))
    slides = slides_of(item)
    outs = []
    for index, slide in enumerate(slides):
        out = os.path.join(tmp, f'card-{index + 1}.png')
        render_png(item, card_html(item, slide, index, len(slides)), width, height, out)
        outs.append(out)
    return outs


def sha256(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def png_size(path: str) -> tuple[int, int]:
    with open(path, 'rb') as f:
        head = f.read(33)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return (0, 0)
    width = int.from_bytes(head[16:20], 'big')
    height = int.from_bytes(head[20:24], 'big')
    return (width, height)


def register(item_id: str, job_id: str, kind: str, path: str, mime: str, local: str, extra: dict | None = None) -> dict:
    width, height = png_size(local) if mime == 'image/png' else (0, 0)
    meta = extra or {}
    return rpc('studio_register_asset', {
        'p_item': item_id,
        'p_job': job_id,
        'p_kind': kind,
        'p_path': path,
        'p_mime': mime,
        'p_width': width or None,
        'p_height': height or None,
        'p_bytes': os.path.getsize(local),
        'p_duration': meta.get('duration_s'),
        'p_checksum': sha256(local),
        'p_meta': meta,
    })


def handle_render_card(job: dict, tmp: str) -> dict:
    item = load_item(job['item_id'])
    paths = card_pngs(item, tmp)
    stored = []
    for index, local in enumerate(paths):
        rev = item.get('revision', 1)
        key = f"{item['id']}/r{rev}/card-{index + 1}-{uuid.uuid4().hex[:6]}.png"
        upload(key, open(local, 'rb').read(), 'image/png')
        register(item['id'], job['id'], 'card', key, 'image/png', local, {'slide': index + 1, 'revision': rev})
        stored.append(key)
    return {'assets': stored, 'item_status': 'review', 'slides': len(stored)}


def handle_render_thumb(job: dict, tmp: str) -> dict:
    item = load_item(job['item_id'])
    out = os.path.join(tmp, 'thumb.png')
    render_png(item, thumb_html(item), 1280, 720, out)
    rev = item.get('revision', 1)
    key = f"{item['id']}/r{rev}/thumb-{uuid.uuid4().hex[:6]}.png"
    upload(key, open(out, 'rb').read(), 'image/png')
    register(item['id'], job['id'], 'thumb', key, 'image/png', out, {'revision': rev})
    return {'assets': [key], 'item_status': 'review'}


def ffprobe_duration(path: str) -> float:
    candidate = os.path.join(os.path.dirname(FFMPEG), 'ffprobe')
    probe = candidate if os.path.exists(candidate) else shutil.which('ffprobe')
    if not probe:
        return 0.0
    try:
        proc = subprocess.run(
            [probe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', path],
            capture_output=True, text=True, timeout=60,
        )
        return float(proc.stdout.strip())
    except Exception:
        return 0.0


def build_srt(item: dict, per_slide: float) -> str:
    lines = []
    slides = slides_of(item)
    for index, slide in enumerate(slides):
        start = index * per_slide
        end = start + per_slide
        def stamp(value: float) -> str:
            ms = int(round(value * 1000))
            return f'{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}'
        text = (slide.get('heading') or '') + ('\n' + slide['body'] if slide.get('body') else '')
        lines.append(f'{index + 1}\n{stamp(start)} --> {stamp(end)}\n{text}\n')
    return '\n'.join(lines)


def handle_encode_video(job: dict, tmp: str) -> dict:
    item = load_item(job['item_id'])
    platform = item.get('platform', 'youtube')
    vertical = platform in ('instagram', 'threads')
    width, height = (1080, 1920) if vertical else (1920, 1080)
    paths = card_pngs(item, tmp)
    per_slide = float((job.get('payload') or {}).get('per_slide') or 2.5)
    concat = os.path.join(tmp, 'concat.txt')
    with open(concat, 'w', encoding='utf-8') as f:
        for path in paths:
            f.write(f"file '{path}'\nduration {per_slide}\n")
        f.write(f"file '{paths[-1]}'\n")
    srt = os.path.join(tmp, 'subs.srt')
    with open(srt, 'w', encoding='utf-8') as f:
        f.write(build_srt(item, per_slide))
    out = os.path.join(tmp, 'video.mp4')
    filter_chain = (
        f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
        f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0e0e12,fps=30,format=yuv420p'
    )
    cmd = [
        FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', concat,
        '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
        '-vf', filter_chain,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', out,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f'ffmpeg encode failed: {proc.stderr[-800:]}')
    duration = ffprobe_duration(out) or round(per_slide * len(paths), 3)
    loudness = measure_loudness(out)
    rev = item.get('revision', 1)
    key = f"{item['id']}/r{rev}/video-{uuid.uuid4().hex[:6]}.mp4"
    upload(key, open(out, 'rb').read(), 'video/mp4')
    register(item['id'], job['id'], 'video', key, 'video/mp4', out,
             {'duration_s': duration, 'width': width, 'height': height, 'loudness': loudness, 'revision': rev})
    subs_key = f"{item['id']}/r{rev}/subs-{uuid.uuid4().hex[:6]}.srt"
    upload(subs_key, open(srt, 'rb').read(), 'text/plain')
    register(item['id'], job['id'], 'subs', subs_key, 'text/plain', srt, {'revision': rev})
    return {'assets': [key, subs_key], 'item_status': 'review', 'duration_s': duration, 'loudness': loudness}


def measure_loudness(path: str) -> dict:
    """EBU R128 라우드니스 + 트루피크 실측(ffmpeg loudnorm 1패스 분석)."""
    cmd = [FFMPEG, '-hide_banner', '-i', path, '-af', "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", '-f', 'null', '-']
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = proc.stderr
    start = text.rfind('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return {'measured': False, 'note': 'loudnorm 분석 출력 없음'}
    try:
        data = json.loads(text[start:end + 1])
        return {
            'measured': True,
            'input_i': data.get('input_i'),
            'input_tp': data.get('input_tp'),
            'input_lra': data.get('input_lra'),
            'target': 'I=-14 LUFS, TP=-1 dBTP',
        }
    except Exception:
        return {'measured': False}


def handle_make_subs(job: dict, tmp: str) -> dict:
    item = load_item(job['item_id'])
    per_slide = float((job.get('payload') or {}).get('per_slide') or 2.5)
    srt = os.path.join(tmp, 'subs.srt')
    with open(srt, 'w', encoding='utf-8') as f:
        f.write(build_srt(item, per_slide))
    rev = item.get('revision', 1)
    key = f"{item['id']}/r{rev}/subs-{uuid.uuid4().hex[:6]}.srt"
    upload(key, open(srt, 'rb').read(), 'application/x-subrip')
    register(item['id'], job['id'], 'subs', key, 'text/plain', srt, {'revision': rev})
    return {'assets': [key]}


def handle_audio_check(job: dict, tmp: str) -> dict:
    item = load_item(job['item_id'])
    assets = rest(f"studio_assets?select=*&item_id=eq.{item['id']}&kind=eq.audio&order=created_at.desc&limit=1")
    if not assets:
        return {'note': 'audio 자산 없음', 'skipped': True}
    asset = assets[0]
    url = f"{SUPABASE_URL}/storage/v1/object/{asset['storage_path']}"
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + SERVICE_KEY, 'apikey': SERVICE_KEY})
    with urllib.request.urlopen(req, timeout=120) as res:
        blob = res.read()
    local = os.path.join(tmp, 'audio.bin')
    open(local, 'wb').write(blob)
    return {'loudness': measure_loudness(local)}


HANDLERS = {
    'render_card': handle_render_card,
    'render_thumb': handle_render_thumb,
    'encode_video': handle_encode_video,
    'make_subs': handle_make_subs,
    'audio_check': handle_audio_check,
}


# --------------------------------------------------------------------------- #
# Loop
# --------------------------------------------------------------------------- #
def preflight() -> None:
    if not SUPABASE_URL or not SERVICE_KEY:
        raise SystemExit('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수가 필요합니다.')
    for binary in (NODE,):
        if not shutil.which(binary) and not os.path.exists(binary):
            raise SystemExit(f'{binary} 를 찾을 수 없습니다.')
    if not shutil.which(FFMPEG) and not os.path.exists(FFMPEG):
        raise SystemExit(f'ffmpeg({FFMPEG}) 를 찾을 수 없습니다.')


def run_once(kinds: list[str] | None = None, limit: int = 3) -> int:
    jobs = rpc('studio_claim_jobs', {'p_worker': WORKER, 'p_limit': limit, 'p_kinds': kinds}) or []
    if not jobs:
        print(f'[{datetime.now(timezone.utc).isoformat()}] 처리할 잡 없음')
        return 0
    done = 0
    for job in jobs:
        kind = job.get('kind')
        handler = HANDLERS.get(kind)
        started = time.time()
        if not handler:
            rpc('studio_finish_job', {'p_job': job['id'], 'p_ok': False, 'p_error': f'워커가 처리하지 않는 잡: {kind}'})
            continue
        tmp = tempfile.mkdtemp(prefix='studio-')
        try:
            result = handler(job, tmp)
            item_status = result.pop('item_status', None)
            rpc('studio_finish_job', {'p_job': job['id'], 'p_ok': True, 'p_result': result, 'p_item_status': item_status})
            done += 1
            print(f"[ok] {kind} job={job['id']} {round(time.time() - started, 1)}s {json.dumps(result, ensure_ascii=False)[:400]}")
        except Exception as exc:  # noqa: BLE001
            message = f'{type(exc).__name__}: {exc}'
            rpc('studio_finish_job', {'p_job': job['id'], 'p_ok': False, 'p_error': message[:900]})
            print(f"[fail] {kind} job={job['id']} {message[:500]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--loop', type=int, default=0, help='초 간격으로 계속 실행')
    parser.add_argument('--kinds', default='', help='쉼표 구분 잡 종류 제한')
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    preflight()
    kinds = [k.strip() for k in args.kinds.split(',') if k.strip()] or None
    if args.loop:
        while True:
            try:
                run_once(kinds, args.limit)
            except Exception as exc:  # noqa: BLE001
                print(f'[loop] {type(exc).__name__}: {exc}')
            time.sleep(args.loop)
    else:
        run_once(kinds, args.limit)


if __name__ == '__main__':
    main()
