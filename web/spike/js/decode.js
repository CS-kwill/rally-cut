// 실측 ① — WebCodecs VideoDecoder 순차 디코딩 처리량 (렌더링 없음, 즉시 close)
import { demux, trackDescription, sleep } from './demux.js';

export async function decodeThroughput(file, { seconds = 60, log }) {
  if (!('VideoDecoder' in window)) throw new Error('WebCodecs VideoDecoder 미지원 브라우저');

  let decoder = null;
  let frames = 0;
  let lastMediaT = 0;
  let codec = '';
  let size = '';
  let supported = null;
  let decErr = null;
  const t0 = performance.now();

  await demux(file, {
    onReady: async (info, mp4file) => {
      const vt = info.videoTracks[0];
      codec = vt.codec;
      size = `${vt.video.width}x${vt.video.height}`;
      const cfg = {
        codec: vt.codec,
        codedWidth: vt.video.width,
        codedHeight: vt.video.height,
      };
      const desc = trackDescription(mp4file, vt.id);
      if (desc) cfg.description = desc;
      try {
        const sup = await VideoDecoder.isConfigSupported(cfg);
        supported = sup.supported;
      } catch (e) {
        supported = null;
        log('isConfigSupported 예외: ' + e.message);
      }
      log(`트랙 ${codec} ${size}, ${vt.nb_samples}샘플, isConfigSupported=${supported}`);
      if (supported === false) throw new Error(`이 브라우저가 코덱을 지원하지 않음: ${codec}`);
      decoder = new VideoDecoder({
        output: (f) => { frames++; f.close(); },
        error: (e) => { decErr = e; },
      });
      decoder.configure(cfg);
    },
    onVideoSample: async (s) => {
      if (decErr) throw new Error('디코더 오류: ' + decErr.message);
      const t = s.cts / s.timescale;
      if (seconds && t > seconds) return false;
      decoder.decode(new EncodedVideoChunk({
        type: s.is_sync ? 'key' : 'delta',
        timestamp: Math.round((1e6 * s.cts) / s.timescale),
        duration: Math.round((1e6 * s.duration) / s.timescale),
        data: s.data,
      }));
      if (t > lastMediaT) lastMediaT = t;
      while (decoder.decodeQueueSize > 40) await sleep(2);
    },
  });

  if (decoder && decoder.state === 'configured') await decoder.flush();
  if (decErr) throw new Error('디코더 오류: ' + decErr.message);

  const elapsed = (performance.now() - t0) / 1000;
  const speedX = lastMediaT / elapsed; // 실시간 대비 배속
  return {
    코덱: `${codec} ${size}`,
    디코딩프레임: frames,
    영상구간_s: +lastMediaT.toFixed(1),
    소요_s: +elapsed.toFixed(1),
    디코딩fps: +(frames / elapsed).toFixed(1),
    실시간대비배속: +speedX.toFixed(2),
    '17분영상_예상_분': speedX > 0 ? +(17 / speedX).toFixed(1) : null,
  };
}
