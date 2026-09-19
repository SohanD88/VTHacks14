(() => {
  const dashboard = document.querySelector('#dashboard');
  const modeler = document.querySelector('#modeler');
  const openButton = document.querySelector('#openModeler');
  const closeButton = document.querySelector('#closeModeler');
  const clock = document.querySelector('#missionClock');
  const toast = document.querySelector('#toast');
  const scenes = new Map();

  function setClock() {
    clock.textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
  }
  setClock();
  setInterval(setClock, 1000);

  function showModeler(updateHash = true) {
    dashboard.classList.remove('is-active');
    dashboard.setAttribute('aria-hidden', 'true');
    modeler.classList.add('is-active');
    modeler.setAttribute('aria-hidden', 'false');
    if (updateHash) history.pushState({ view: 'modeler' }, '', '#modeler');
    requestAnimationFrame(() => scenes.get('modeler')?.resize());
  }

  function showDashboard(updateHash = true) {
    modeler.classList.remove('is-active');
    modeler.setAttribute('aria-hidden', 'true');
    dashboard.classList.add('is-active');
    dashboard.setAttribute('aria-hidden', 'false');
    if (updateHash) history.pushState({ view: 'dashboard' }, '', location.pathname);
    requestAnimationFrame(() => scenes.get('preview')?.resize());
  }

  openButton.addEventListener('click', () => showModeler());
  closeButton.addEventListener('click', () => showDashboard());
  window.addEventListener('popstate', () => location.hash === '#modeler' ? showModeler(false) : showDashboard(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modeler.classList.contains('is-active')) showDashboard();
  });

  function notify(message) {
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove('is-visible'), 1800);
  }

  document.querySelectorAll('.tool-list button').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.tool-list button').forEach((item) => item.classList.remove('is-selected'));
      button.classList.add('is-selected');
      notify(`${button.dataset.tool} tool selected`);
    });
  });

  document.querySelectorAll('[data-agent]').forEach((button) => {
    button.addEventListener('click', () => notify(`${button.dataset.agent} is analyzing the scene`));
  });

  const agentDock = document.querySelector('.agent-dock');
  const toggleAgents = document.querySelector('#toggleAgents');
  toggleAgents.addEventListener('click', () => {
    const collapsed = agentDock.classList.toggle('is-collapsed');
    toggleAgents.textContent = collapsed ? 'Expand' : 'Collapse';
    toggleAgents.setAttribute('aria-expanded', String(!collapsed));
  });

  document.querySelector('.primary-action').addEventListener('click', () => notify('Model prepared for export'));

  class WireScene {
    constructor(canvas, mode) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.mode = mode;
      this.yaw = mode === 'preview' ? -0.52 : -0.62;
      this.pitch = mode === 'preview' ? 0.55 : 0.48;
      this.zoom = mode === 'preview' ? 1 : 1.08;
      this.dragging = false;
      this.last = { x: 0, y: 0 };
      this.bind();
      this.resize();
    }

    bind() {
      const begin = (x, y) => { this.dragging = true; this.last = { x, y }; };
      const move = (x, y) => {
        if (!this.dragging) return;
        this.yaw += (x - this.last.x) * .008;
        this.pitch = Math.max(.12, Math.min(1.12, this.pitch + (y - this.last.y) * .006));
        this.last = { x, y };
      };
      this.canvas.addEventListener('pointerdown', (e) => { this.canvas.setPointerCapture(e.pointerId); begin(e.clientX, e.clientY); });
      this.canvas.addEventListener('pointermove', (e) => move(e.clientX, e.clientY));
      this.canvas.addEventListener('pointerup', () => { this.dragging = false; });
      this.canvas.addEventListener('wheel', (e) => { e.preventDefault(); this.zoom = Math.max(.68, Math.min(1.65, this.zoom - e.deltaY * .0008)); }, { passive: false });
      window.addEventListener('resize', () => this.resize());
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = Math.max(1, Math.round(rect.width * dpr));
      this.canvas.height = Math.max(1, Math.round(rect.height * dpr));
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.width = rect.width;
      this.height = rect.height;
    }

    project([x, y, z]) {
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
      const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
      const rx = x * cy - z * sy;
      const rz = x * sy + z * cy;
      const ry = y * cp - rz * sp;
      const depth = y * sp + rz * cp;
      const scale = Math.min(this.width / 12, this.height / 8) * this.zoom;
      return [this.width * .5 + rx * scale, this.height * .46 - ry * scale, depth];
    }

    line(a, b, color = 'rgba(110, 240, 210, .55)', width = 1) {
      const p1 = this.project(a), p2 = this.project(b);
      this.ctx.beginPath(); this.ctx.moveTo(p1[0], p1[1]); this.ctx.lineTo(p2[0], p2[1]);
      this.ctx.strokeStyle = color; this.ctx.lineWidth = width; this.ctx.stroke();
    }

    polygon(points, fill, stroke = 'rgba(120, 205, 190, .35)') {
      const p = points.map((point) => this.project(point));
      this.ctx.beginPath(); this.ctx.moveTo(p[0][0], p[0][1]); p.slice(1).forEach((q) => this.ctx.lineTo(q[0], q[1])); this.ctx.closePath();
      this.ctx.fillStyle = fill; this.ctx.fill(); this.ctx.strokeStyle = stroke; this.ctx.lineWidth = 1; this.ctx.stroke();
    }

    box(x, y, z, w, h, d, color = 'rgba(46, 101, 96, .34)') {
      const v = [[x,y,z],[x+w,y,z],[x+w,y,z+d],[x,y,z+d],[x,y+h,z],[x+w,y+h,z],[x+w,y+h,z+d],[x,y+h,z+d]];
      this.polygon([v[0],v[1],v[5],v[4]], color);
      this.polygon([v[1],v[2],v[6],v[5]], 'rgba(35, 76, 80, .34)');
      this.polygon([v[4],v[5],v[6],v[7]], 'rgba(77, 142, 125, .28)');
      [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]].forEach(([a,b]) => this.line(v[a],v[b],'rgba(120, 225, 199, .52)',.8));
    }

    label(text, point, color = '#6df6d1') {
      const p = this.project(point);
      this.ctx.font = '10px SFMono-Regular, monospace'; this.ctx.fillStyle = color;
      this.ctx.fillText(text, p[0] + 6, p[1] - 6);
      this.ctx.fillRect(p[0] - 2, p[1] - 2, 4, 4);
    }

    draw(time) {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.width, this.height);
      if (!this.dragging && this.mode === 'preview') this.yaw += .00035;

      for (let i = -5; i <= 5; i++) {
        this.line([-5, 0, i], [5, 0, i], 'rgba(102, 158, 160, .09)');
        this.line([i, 0, -5], [i, 0, 5], 'rgba(102, 158, 160, .09)');
      }

      this.polygon([[-4,0,-3.3],[4,0,-3.3],[4,0,3.3],[-4,0,3.3]], 'rgba(30, 73, 72, .2)', 'rgba(105, 246, 209, .38)');
      this.polygon([[-4,0,-3.3],[-4,2.5,-3.3],[4,2.5,-3.3],[4,0,-3.3]], 'rgba(28, 63, 69, .24)');
      this.polygon([[-4,0,-3.3],[-4,0,3.3],[-4,2.5,3.3],[-4,2.5,-3.3]], 'rgba(26, 55, 63, .26)');
      this.box(-2.7,0,-1.7,1.7,.72,.85);
      this.box(.45,0,-2.4,2.3,.8,.75,'rgba(41, 84, 96, .34)');
      this.box(1.45,0,.4,1.7,.42,1.25,'rgba(55, 104, 92, .3)');
      this.box(-2.25,0,1.25,.75,.95,.75,'rgba(49, 91, 86, .3)');
      this.box(-.15,0,.55,.72,.72,.72,'rgba(57, 102, 97, .32)');

      const pulse = .6 + Math.sin(time * .002) * .2;
      this.label('ENTRY / D-05', [3.65,1.6,-3.28], `rgba(105,246,209,${pulse})`);
      this.label('OBJECT / 09', [-.1,.85,.55], '#ffca69');
      this.label('CAM-04', [-3.6,.12,2.8], '#78a7ff');
      this.line([-3.6,.08,2.8],[-2.6,.08,1.6],'rgba(120,167,255,.75)',2);
      this.line([-2.6,.08,1.6],[-1.2,.08,.8],'rgba(120,167,255,.75)',2);
      this.line([-1.2,.08,.8],[.2,.08,-.2],'rgba(120,167,255,.75)',2);
      this.line([.2,.08,-.2],[1.8,.08,-1.35],'rgba(120,167,255,.75)',2);
      requestAnimationFrame((t) => this.draw(t));
    }

    reset() { this.yaw = -.62; this.pitch = .48; this.zoom = 1.08; }
  }

  document.querySelectorAll('[data-scene]').forEach((canvas) => {
    const scene = new WireScene(canvas, canvas.dataset.scene);
    scenes.set(canvas.dataset.scene, scene);
    requestAnimationFrame((t) => scene.draw(t));
  });

  document.querySelector('#zoomIn').addEventListener('click', () => { scenes.get('modeler').zoom = Math.min(1.65, scenes.get('modeler').zoom + .12); });
  document.querySelector('#zoomOut').addEventListener('click', () => { scenes.get('modeler').zoom = Math.max(.68, scenes.get('modeler').zoom - .12); });
  document.querySelector('#resetView').addEventListener('click', () => scenes.get('modeler').reset());

  if (location.hash === '#modeler') showModeler(false);
})();
