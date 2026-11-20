'use strict';

// NETJammer theme art: which theme is active, where each theme's artwork lives,
// what to show until the host supplies new art, and the album-art tint.
//
// Artwork is plain files the host can replace without touching code:
//   art/<theme>/scene.png   full scene with the guy (wide, guy on the right)
//   art/<theme>/guy.png     optional cut-out of the guy, layered on top and
//                           given a gentle bob while music plays (when you add
//                           it, make scene.png the empty room)
//   art/face.png            face mark for the logo and favicon
// Missing files fall back: Neon Club borrows the Listening Room scene with a
// neon treatment, Arcade draws its own pixel scene below, and the face mark
// falls back to art/face.svg.
(function () {
  var BASE = '/netjammer/art/';
  var THEMES = [
    { id: 'listening-room', label: 'Listening Room', blurb: 'Dark and cozy, for late nights.', hue: 212 },
    { id: 'daylight', label: 'Daylight', blurb: 'The same room in soft daylight.', hue: 150 },
    { id: 'neon-club', label: 'Neon Club', blurb: 'Loud, bright, the party is on.', hue: 320 },
    { id: 'arcade', label: 'Arcade', blurb: 'Pixel art, retro game style.', hue: 250 }
  ];
  var IDS = THEMES.map(function (t) { return t.id; });
  var LEGACY = { dark: 'listening-room', light: 'daylight' };

  function normalise(id) {
    if (LEGACY[id]) return LEGACY[id];
    return IDS.indexOf(id) !== -1 ? id : 'listening-room';
  }
  function read() {
    try { return normalise(localStorage.getItem('netjammerTheme')); } catch (e) { return 'listening-room'; }
  }
  function save(id) {
    try { localStorage.setItem('netjammerTheme', id); } catch (e) { /* private mode */ }
  }

  // Probe a file once; remember whether it exists.
  var probes = {};
  function probe(url, cb) {
    if (probes[url] !== undefined) {
      if (probes[url] === 'pending') { probes[url + '#cbs'].push(cb); return; }
      cb(probes[url]);
      return;
    }
    probes[url] = 'pending';
    probes[url + '#cbs'] = [cb];
    var img = new Image();
    function done(ok) {
      probes[url] = ok;
      probes[url + '#cbs'].forEach(function (f) { f(ok); });
    }
    img.onload = function () { done(true); };
    img.onerror = function () { done(false); };
    img.src = url;
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // ===== Arcade: a pixel scene drawn in code (used until art/arcade/scene.png exists) =====
  var GUY = [
    "............KKKKKKK.............",
    "..........KKHHHHHHHKK...........",
    ".........KHHHHhhhhHHHK..........",
    "........KHHHHHHHHHHhHHK.........",
    "........KHHHHHHHHHHHHHK.........",
    "........KHHHHHHHHHHHHK..........",
    "........KHHHHHKKKKKKK...........",
    "........KHHSSSSSSSSSSK..........",
    ".......KsKHSSSSSSSSSSK..........",
    ".......KsKSKKKSSKKKSSK..........",
    ".......KsKKWWWKKWWWKSK..........",
    "........KKKWKWKSKWKWKSK.........",
    ".........KSKKKSSSKKKSSK.........",
    ".........KSSSSSSsSSSSSK.........",
    ".........KSSSSSSssSSSSK.........",
    "......M..KSMMMMMMMMMMSK..M......",
    "......MMMKMMMMMMMMMMMMMKMMM.....",
    "......MMMMMMKSSSSSSKMMMMMM......",
    ".........KSSSSSSSSSSSSK.........",
    "..........KSSSSSSSSSSK..........",
    "...........KKSSSSSSKK...........",
    "............KSSSSSSK............",
    "..........KKPBBBBBBPKK..........",
    "........KKPPPKBBBBKPPPKK........",
    ".......KPPpPPPKBBKPPpPPPK.......",
    "......KPPPpPPPPKBBPPPpPPPK......",
    "......KqqqpqqqqPBBPqqqpqqqK.....",
    ".....KPPPPpPPPPPBBPPPPpPPPPK....",
    ".....KPPPPpPPPPPBBPPPPpPPPPPK...",
    ".....KPPPPpPPPPPBBPPPPpPKPPPPK..",
    ".....KqqqqpqqqqqBBqqqqpqKKqqqqK.",
    ".....KPPPPpPPPPPBBPPPPpPK.KPPPPK",
    ".....KPPPPpPPPPPBBPPPPpPK..KPPSK",
    "....KPPPPKpPPPPPBBPPPPpPK...KSSK",
    "....KqqqqKpqqqqqBBqqqqpqK....KK.",
    "....KPPPPKpPPPPPBBPPPPpPK.......",
    "....KPPPPKpPPPPPBBPPPPpPK.......",
    "....KPPPPKpPPPPPBBPPPPpPK.......",
    "....KqqqqKKKKKKKKKKKKKKKK.......",
    "....KPPPPKJJJJJJJJJJJJJJK.......",
    "....KSSSKKJJJJJJJjJJJJJJK.......",
    "....KSSSSKJJJJJJJjJJJJJJK.......",
    ".....KSSKKJJJJJJJjJJJJJJK.......",
    "......KK.KJJJJJJJjJJJJJJK.......",
    ".........KJJJJJJJjJJJJJJK.......",
    ".........KJJJJJJKKJJJJJJK.......",
    ".........KJJJJJJK.KJJJJJK.......",
    ".........KJJJJJJK.KJJJJJK.......",
    ".........KJJJJJJK.KJJJJJK.......",
    ".........KJJJJJJK.KJJJJJK.......",
    ".........KjJJJJJK.KJJJJjK.......",
    ".........KjJJJJJK.KJJJJjK.......",
    "........KOOOOOOOK.KOOOOOOOK.....",
    "........KOOOOOOOK.KOOOOOOOOK....",
    "........KKKKKKKKK.KKKKKKKKKK...."
  ];
  var GUY_PAL = {
    K: '#1a1020', H: '#6e4127', h: '#a3683f', S: '#f2c7a2', s: '#d39a74', W: '#e8f6ff',
    M: '#b06a2c', P: '#3f6b52', p: '#86c06a', q: '#284636', B: '#7d92b8',
    J: '#34465c', j: '#26333f', O: '#3a2416'
  };
  var NOTE = ['..KK', '..KKK', '..K.K', '..K..', '..K..', 'KKK..', 'KKK..'];
  var PHONES = ['..KKKKKK..', '.K......K.', 'K........K', 'K........K', 'KK......KK', 'KKK....KKK', 'KKK....KKK', '.K......K.'];
  var BOOMBOX = [
    '.....KKKKKKKKKKKKKKKK.....',
    '.....K..............K.....',
    'KKKKKKKKKKKKKKKKKKKKKKKKKK',
    'KGGGGGGGGGGGGGGGGGGGGGGGGK',
    'KGKKKKKGGGGGGGGGGGGKKKKKGK',
    'KKDDDDDKGGLLLLLLGGKDDDDDKK',
    'KKDDTDDKGGLLLLLLGGKDDTDDKK',
    'KKDTTTDKGGGGGGGGGGKDTTTDKK',
    'KKDDTDDKGGRGYGRGGGKDDTDDKK',
    'KKDDDDDKGGGGGGGGGGKDDDDDKK',
    'KGKKKKKGGGGGGGGGGGGKKKKKGK',
    'KGGGGGGGGGGGGGGGGGGGGGGGGK',
    'KKKKKKKKKKKKKKKKKKKKKKKKKK'
  ];
  var BOX_PAL = { K: '#0d0a22', G: '#c9c6e6', D: '#2b2552', T: '#5b51a8', L: '#7ef0c4', R: '#ff5d73', Y: '#ffd23f' };

  function sprite(ctx, rows, pal, x0, y0, colour) {
    for (var y = 0; y < rows.length; y++) {
      for (var x = 0; x < rows[y].length; x++) {
        var c = rows[y][x];
        if (c === '.') continue;
        ctx.fillStyle = colour || pal[c];
        if (!ctx.fillStyle) continue;
        ctx.fillRect(x0 + x, y0 + y, 1, 1);
      }
    }
  }

  // Deterministic "random" so the sky looks the same on every screen.
  function rng(seed) {
    return function () {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };
  }

  var W = 160, H = 100;
  var stars = (function () {
    var r = rng(42), out = [];
    for (var i = 0; i < 46; i++) out.push({ x: Math.floor(r() * W), y: Math.floor(r() * 52), big: r() > 0.82, tw: r() > 0.6 });
    return out;
  })();

  function drawPixelScene(canvas, frame) {
    var ctx = canvas.getContext('2d');
    canvas.width = W;
    canvas.height = H;
    ctx.imageSmoothingEnabled = false;
    // Sky: stepped bands with a dithered seam between them.
    var bands = ['#100b2e', '#160f3d', '#1d144d', '#26195d', '#30206c'];
    var bh = 12;
    for (var b = 0; b < bands.length; b++) {
      ctx.fillStyle = bands[b];
      ctx.fillRect(0, b * bh, W, bh + (b === bands.length - 1 ? 40 : 0));
      if (b > 0) {
        ctx.fillStyle = bands[b - 1];
        for (var dx = 0; dx < W; dx += 2) ctx.fillRect(dx + (b % 2), b * bh, 1, 1);
      }
    }
    // Stars (some twinkle on alternate frames).
    stars.forEach(function (s, i) {
      var on = !s.tw || ((frame + i) % 3 !== 0);
      if (!on) return;
      ctx.fillStyle = i % 5 === 0 ? '#ffd86b' : '#e9e6ff';
      ctx.fillRect(s.x, s.y, 1, 1);
      if (s.big) {
        ctx.fillRect(s.x - 1, s.y, 3, 1);
        ctx.fillRect(s.x, s.y - 1, 1, 3);
      }
    });
    // Moon.
    ctx.fillStyle = '#fff1bf';
    for (var my = -6; my <= 6; my++) {
      for (var mx = -6; mx <= 6; mx++) {
        if (mx * mx + my * my <= 38) ctx.fillRect(56 + mx, 16 + my, 1, 1);
      }
    }
    ctx.fillStyle = '#e8d38f';
    ctx.fillRect(53, 14, 2, 2); ctx.fillRect(58, 18, 3, 2); ctx.fillRect(57, 12, 1, 1);
    // Hills (back) and ground (front), echoing the green hills in the illustration.
    for (var x = 0; x < W; x++) {
      var back = 70 + Math.round(Math.sin(x / 17) * 4 + Math.sin(x / 7) * 1.5);
      ctx.fillStyle = '#23463f';
      ctx.fillRect(x, back, 1, H - back);
      var front = 82 + Math.round(Math.sin((x + 30) / 23) * 3);
      ctx.fillStyle = '#2f6b4c';
      ctx.fillRect(x, front, 1, H - front);
      ctx.fillStyle = '#47915f';
      ctx.fillRect(x, front, 1, 1);
      if (x % 7 === 0) ctx.fillRect(x, front - 1, 1, 1);
    }
    // Purple stage disc under the guy, like the illustration's.
    ctx.fillStyle = '#3d2f86';
    for (var ey = 0; ey < 10; ey++) {
      var half = Math.round(Math.sqrt(1 - Math.pow((ey - 9) / 10, 2)) * 34);
      ctx.fillRect(112 - half, 90 + ey, half * 2, 1);
    }
    ctx.fillStyle = '#5546b0';
    ctx.fillRect(84, 90, 56, 1);
    // Boombox on the left, notes in the air, headphones by his hand.
    sprite(ctx, BOOMBOX, BOX_PAL, 64, 76);
    sprite(ctx, NOTE, null, 70, 58, '#7ef0c4');
    sprite(ctx, NOTE, null, 82, 40, '#ffd23f');
    sprite(ctx, NOTE, null, 140, 72, '#ff7ab6');
    sprite(ctx, PHONES, null, 138, 50, '#7ef0c4');
    // The guy.
    sprite(ctx, GUY, GUY_PAL, 96, 44);
  }

  var arcadeTimer = null;
  function startArcade(canvas, playing) {
    var frame = 0;
    drawPixelScene(canvas, frame);
    if (arcadeTimer) { clearInterval(arcadeTimer); arcadeTimer = null; }
    if (playing && !reducedMotion()) {
      arcadeTimer = setInterval(function () { frame++; drawPixelScene(canvas, frame); }, 700);
    }
  }

  // ===== Applying a theme's art =====
  var state = { theme: null, playing: false };

  function applyArt() {
    var theme = state.theme;
    var root = document.documentElement;
    var img = document.getElementById('nj-scene');
    var canvas = document.getElementById('nj-pixel');
    if (!img || !canvas) return;

    probe(BASE + theme + '/scene.png', function (ok) {
      if (state.theme !== theme) return;
      if (ok) {
        img.src = BASE + theme + '/scene.png';
        root.setAttribute('data-art', 'custom');
      } else if (theme === 'arcade') {
        root.setAttribute('data-art', 'pixel');
      } else {
        // Neon Club (and anything else missing art) borrows the Listening Room scene.
        img.src = BASE + 'listening-room/scene.png';
        root.setAttribute('data-art', 'fallback');
      }
      if (root.getAttribute('data-art') === 'pixel') startArcade(canvas, state.playing);
      else if (arcadeTimer) { clearInterval(arcadeTimer); arcadeTimer = null; }
    });
    probe(BASE + theme + '/guy.png', function (ok) {
      if (state.theme !== theme) return;
      var guy = document.getElementById('nj-guy');
      if (ok) {
        if (!guy) {
          guy = document.createElement('img');
          guy.id = 'nj-guy';
          guy.className = 'scene-guy';
          guy.alt = '';
          canvas.parentNode.insertBefore(guy, canvas.nextSibling);
        }
        guy.src = BASE + theme + '/guy.png';
        root.setAttribute('data-guy', 'on');
      } else {
        if (guy) guy.parentNode.removeChild(guy);
        root.removeAttribute('data-guy');
      }
    });
  }

  var faceSrc = BASE + 'face.svg', faceListeners = [];
  function applyFace() {
    probe(BASE + 'face.png', function (ok) {
      var src = BASE + (ok ? 'face.png' : 'face.svg');
      if (src !== faceSrc) {
        faceSrc = src;
        faceListeners.forEach(function (f) { f(src); });
      }
      var icon = document.getElementById('nj-favicon');
      if (icon) {
        icon.setAttribute('href', src);
        icon.setAttribute('type', ok ? 'image/png' : 'image/svg+xml');
      }
    });
  }

  function setTheme(id) {
    id = normalise(id);
    state.theme = id;
    document.documentElement.setAttribute('data-theme', id);
    var t = THEMES[IDS.indexOf(id)];
    document.documentElement.style.setProperty('--theme-hue', t.hue);
    save(id);
    applyArt();
    applyFace();
    return id;
  }

  function setPlaying(playing) {
    state.playing = !!playing;
    if (document.documentElement.getAttribute('data-art') === 'pixel') {
      var canvas = document.getElementById('nj-pixel');
      if (canvas) startArcade(canvas, state.playing);
    }
  }

  // ===== Album-art tint =====
  // Average the album art's saturated pixels into one hue. Each theme decides
  // how much of that hue reaches its glow, so text contrast never depends on it.
  // Images served without CORS headers can't be read; the theme's own hue stays.
  var tintSeq = 0;
  function tint(url) {
    var root = document.documentElement;
    var seq = ++tintSeq;
    if (!url) { root.style.removeProperty('--tint-hue'); root.removeAttribute('data-tinted'); return; }
    var img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = function () {
      if (seq !== tintSeq) return;
      try {
        var c = document.createElement('canvas');
        c.width = c.height = 24;
        var ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0, 24, 24);
        var d = ctx.getImageData(0, 0, 24, 24).data;
        var sx = 0, sy = 0, wsum = 0;
        for (var i = 0; i < d.length; i += 4) {
          var r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
          var max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
          var sat = max === min ? 0 : (max - min) / (1 - Math.abs(2 * l - 1));
          if (sat < 0.2 || l < 0.12 || l > 0.92) continue;
          var h;
          if (max === r) h = ((g - b) / (max - min)) % 6;
          else if (max === g) h = (b - r) / (max - min) + 2;
          else h = (r - g) / (max - min) + 4;
          h = h * 60 * Math.PI / 180;
          var w = sat * (1 - Math.abs(l - 0.5));
          sx += Math.cos(h) * w; sy += Math.sin(h) * w; wsum += w;
        }
        if (wsum < 3) { root.style.removeProperty('--tint-hue'); root.removeAttribute('data-tinted'); return; }
        var hue = Math.round((Math.atan2(sy, sx) * 180 / Math.PI + 360) % 360);
        root.style.setProperty('--tint-hue', hue);
        root.setAttribute('data-tinted', 'true');
      } catch (e) {
        root.style.removeProperty('--tint-hue');
        root.removeAttribute('data-tinted');
      }
    };
    img.onerror = function () {
      if (seq !== tintSeq) return;
      root.style.removeProperty('--tint-hue');
      root.removeAttribute('data-tinted');
    };
    img.src = url;
  }

  window.NJArt = {
    themes: THEMES,
    read: read,
    setTheme: setTheme,
    setPlaying: setPlaying,
    tint: tint,
    faceSrc: function () { return faceSrc; },
    onFace: function (f) { faceListeners.push(f); },
    refresh: function () { applyArt(); applyFace(); }
  };
})();
