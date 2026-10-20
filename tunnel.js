import localtunnel from 'localtunnel';

const PORT = 8000;

(async () => {
  try {
    const tunnel = await localtunnel({ port: PORT });
    console.log('PUBLIC_URL: ' + tunnel.url);
    tunnel.on('close', () => {
      console.log('Tunnel closed');
    });
  } catch (err) {
    console.error('Tunnel error:', err);
  }
})();
