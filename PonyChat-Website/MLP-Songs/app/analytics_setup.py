"""Run on the music host during deployment; safely enable persistent statistics."""
from pathlib import Path
import subprocess


def configure():
    site = Path('/etc/nginx/sites-available/mlp-music')
    original = site.read_text('utf-8')
    if 'mlp-music-analytics.log' not in original:
        # A server-level log includes media, API and website requests.
        updated = original.replace('    server_name ', '    access_log /var/log/nginx/mlp-music-analytics.log combined;\n    server_name ')
        if updated == original:
            raise RuntimeError('Cannot locate music nginx server block')
        site.write_text(updated, 'utf-8')
        result = subprocess.run(['nginx', '-t'], check=False)
        if result.returncode:
            site.write_text(original, 'utf-8')
            raise RuntimeError('Music analytics nginx configuration failed validation')
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    dropin = Path('/etc/systemd/system/mlp-music.service.d/analytics.conf')
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text('[Service]\nEnvironment=MLP_ANALYTICS_DB=/data/mlp-music/analytics.sqlite3\nEnvironment=MLP_ANALYTICS_TOKEN_FILE=/etc/mlp-music/analytics-token\n', 'utf-8')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)


if __name__ == '__main__':
    configure()
