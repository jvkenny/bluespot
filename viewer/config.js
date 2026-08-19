// Where the PMTiles archives are served from.
//   localhost → the gitignored viewer/data symlink into Google Drive (fast,
//               no egress, and what you edit against)
//   anywhere else → Cloudflare R2, which is what a published copy reads.
//                   Range + CORS verified 2026-08-18.
// Override by setting window.BLUESPOT_DATA_BASE before this file loads.
window.BLUESPOT_DATA_BASE = window.BLUESPOT_DATA_BASE ||
  (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)
    ? 'data/'
    : 'https://pub-13602ea3d1644313a463acafbbee7ec0.r2.dev/');
