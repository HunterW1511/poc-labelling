// P.7.4: modo guiado. Un proyecto a la vez, sus 10 pasos y una sola cosa que hacer en cada uno. El paso lo decide
// guia.py (t.siguiente); aqui solo se pinta y se llama a las mismas acciones de la lista blanca (/api/accion), con
// reporte y confirmacion. El modo avanzado (index.html) no cambia. Usa los globales de index.html: $, esc, api, ACC,
// ULTIMO, LS_URL, DAEMON, TRAB, PENDIENTE, FASES, DEFECTOS, correrAccion, sondear, cargarProyectos, cargarServicios.
let GSEL = null, GVER = null, GNUEVO = false, GDET = {}, GPOLL = null, GDAEMON = 0, GNOMBRE = "";
let GREC = null, GBLOB = null, GEXT = "", GT0 = 0, GTREC = null, GMODO = "grabar";
const G = s => document.getElementById(s);
const gguardar = () => { try { localStorage.setItem("xd_gsel", GSEL || ""); } catch (e) {} };
try { GSEL = localStorage.getItem("xd_gsel") || null; } catch (e) {}

function gslug(nombre) {
  return nombre.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 40);
}
function gcasos() { return ULTIMO.filter(t => t.slug && !(t.protegido || t.borrado) && !/-ref$/.test(t.slug)); }
function gtar() { return gcasos().find(t => t.slug === GSEL) || null; }
function gpaso(t) { return t ? ((t.siguiente || {}).paso || 1) : 1; }
function gbtn(txt, attrs, pri) { return '<button class="gbtn' + (pri ? " pri" : "") + '" ' + attrs + ">" + txt + "</button>"; }
function gbarra(v, tot) {
  const p = tot ? Math.round(100 * v / tot) : 0;
  return '<div class="gprog"><div style="width:' + p + '%"></div></div><span class="chico">' + v + " de " + tot + "</span>";
}

// ---- estado de servicios y del automatico (barra de arriba)
function gEstado() {
  const s = window.SERV || {}, e = s.estado || {}, d = DAEMON || {};
  const pt = (ok, txt) => '<span class="gpunto ' + (ok ? "ok" : "mal") + '"></span>' + txt;
  G("gserv").innerHTML = pt(s.label_studio, "Label Studio") + pt(s.motor, "Motor") + pt(e.listo, "Clic SAM 3");
  G("gauto").innerHTML = d.activo
    ? '<span class="gpunto ok"></span>Automatico <b>encendido</b> <span class="chico">(' +
      (d.estado === "ciclo" ? "trabajando" : "revisa Kaggle a las " + esc(d.proximo || "-")) + ")</span> " + gbtn("Apagar", 'data-g="auto-off"')
    : '<span class="gpunto mal"></span>Automatico <b>apagado</b> <span class="chico">(envia y trae de Kaggle solo)</span> ' +
      gbtn("Encender", 'data-g="auto-on"', true);
}

// ---- lista de proyectos (izquierda)
function gLista() {
  const cs = gcasos();
  G("glista").innerHTML = cs.map(t => {
    const p = gpaso(t), sel = !GNUEVO && t.slug === GSEL;
    return '<button class="gcaso' + (sel ? " sel" : "") + '" data-gsel="' + esc(t.slug) + '"><b>' + esc(t.titulo) +
      '</b><span class="chico">Paso ' + p + " de " + FASES.length + ": " + esc(FASES[p - 1] || "") + "</span></button>";
  }).join("") + '<button class="gcaso nuevo' + (GNUEVO ? " sel" : "") + '" data-g="nuevo">+ Nuevo proyecto</button>';
}

// ---- pasos (arriba del panel)
function gPasos(t) {
  const p = GNUEVO ? 1 : gpaso(t), v = GVER || p;
  G("gpasos").innerHTML = FASES.map((f, i) => {
    const k = i + 1, c = k < p ? "hecho" : k === p ? "actual" : "futuro";
    return '<li class="' + c + (k === v ? " visto" : "") + '"' + (k <= p && !GNUEVO ? ' data-gver="' + k + '"' : "") + ">" +
      '<span class="gnum">' + (k < p ? "&#10003;" : k) + "</span>" + esc(f) + "</li>";
  }).join("");
}

// ---- contenido de cada paso
const PASO = {};
PASO[1] = (t, actual) => {
  if (t && !GNUEVO) return '<p>Proyecto <b>' + esc(t.titulo) + "</b> creado (nombre corto <code>" + esc(t.slug) + "</code>).</p>";
  return "<p>Ponle un nombre al proyecto, como quieras verlo en Label Studio.</p>" +
    '<div class="fila"><input id="gnombre" type="text" placeholder="Conteo de tornillos" style="width:280px" value="' + esc(GNOMBRE) + '">' +
    gbtn("Crear proyecto", 'data-g="crear"', true) + '</div><p class="chico" id="gslugv"></p>';
};
PASO[2] = (t, actual) => {
  const g = t.siguiente || {}, a = t.asistente || {}, d = GDET[t.slug];
  if (!actual) return "<p>Descripcion aplicada" + (t.fotos ? ": " + t.fotos.length + " carpetas de fotos (" +
    t.fotos.map(f => esc(f.carpeta)).join(", ") + ")." : ".") + "</p>";
  if ((t.spec_errores || []).length) return '<div class="avisos">' + lista(t.spec_errores) + "</div><p>Corrige " +
    "<code>motor/proyectos/" + esc(t.slug) + "/spec.json</code> y valida.</p>" + gbtn("Validar", 'data-g="accion"', true);
  if (a.ultimo === "pendiente") return '<p class="gespera">El asistente esta leyendo tu descripcion en Kaggle (unos 7 min).</p>' + gAutoNota();
  if (t.spec && !t.n) return "<p>La descripcion esta lista. Ahora se crea el proyecto en Label Studio con sus etiquetas.</p>" +
    gbtn("Crear en Label Studio", 'data-g="accion"', true);
  if (a.ultimo === "resultado" && !a.aplicada) return gEntendio(t, d);
  let h = a.ultimo === "error" ? '<div class="avisos">El asistente fallo; vuelve a intentarlo.' +
    (d && d.error_colab ? '<pre class="mini">' + esc(d.error_colab.slice(-800)) + "</pre>" : "") + "</div>" : "";
  h += "<p>Cuenta que quieres detectar y contar: que objetos, como se ven, cuantos puede haber por foto y donde se toman las fotos.</p>" +
    '<div class="gtabs"><button class="' + (GMODO === "grabar" ? "sel" : "") + '" data-gmodo="grabar">Grabar</button>' +
    '<button class="' + (GMODO === "escribir" ? "sel" : "") + '" data-gmodo="escribir">Escribir</button></div>';
  h += GMODO === "grabar"
    ? '<div class="fila">' + gbtn(GREC ? "Detener" : "Grabar", 'id="ggrabar" data-g="grabar"', !GREC) +
      '<span id="grecinfo" class="chico">' + (GBLOB ? "Grabacion lista: escuchala antes de enviar." : "") + "</span></div>" +
      '<audio id="gaudio" controls' + (GBLOB ? "" : ' style="display:none"') + "></audio>"
    : '<textarea id="gtexto" placeholder="Quiero contar tornillos y tuercas en una charola..."></textarea>';
  h += '<div class="fila" style="margin-top:8px">' + gbtn("Enviar al asistente", 'data-g="enviar"', true) +
    '<button class="glink" data-g="plantilla">Prefiero llenar una plantilla a mano</button></div>';
  return h;
};
function gEntendio(t, d) {
  if (!d) { gDetalle(t.slug); return '<p class="chico">Cargando lo que entendio el asistente...</p>'; }
  const r = d.resultado || {}, errs = (d.errores || []).concat(r.problemas || []);
  let h = "<p>Esto entendio el asistente. Si algo esta mal, corrigelo abajo con tus palabras.</p>";
  if (r.transcripcion) h += '<p class="chico"><b>Lo que dijiste:</b> ' + esc(r.transcripcion) + "</p>";
  if (d.clases) h += "<h3>Que va a contar</h3>" + tabla(["Objeto", "Maximo por foto"], d.clases.map(c => [c.nombre, c.max == null ? "-" : c.max]));
  if (d.plan) h += "<h3>Fotos que vas a tomar</h3>" + tabla(["Carpeta", "Fotos", "Para que"], d.plan.map(f => [f.carpeta, f.fotos, f.motivo]));
  if ((r.preguntas || []).length) h += "<h3>Preguntas del asistente</h3>" + lista(r.preguntas);
  if (errs.length) h += '<div class="avisos">' + lista(errs) + "</div>";
  h += '<textarea id="gresp" placeholder="Respuestas o correcciones (opcional)"></textarea><div class="fila" style="margin-top:8px">' +
    gbtn("Se ve bien: aplicar", 'data-g="aplicar"' + (errs.length ? " data-off disabled" : ""), true) + gbtn("Enviar correcciones", 'data-g="corregir"') + "</div>";
  return h;
}
PASO[3] = (t, actual) => {
  const fs = t.fotos || [], tareas = (t.ls || {}).task_number || 0, tienes = fs.reduce((x, f) => x + f.tienes, 0);
  let h = actual ? "<p>Toma las fotos de cada carpeta (el plan dice cuantas). Tambien puedes copiarlas a mano a " +
    "<code>mis_imagenes/" + esc(t.slug) + "/&lt;carpeta&gt;</code> y luego subirlas.</p>" : "<p>Fotos listas: " + tienes + " en Label Studio.</p>";
  h += tabla(["Carpeta", "Tipo", "Tienes", "Plan"], fs.map(f => [f.carpeta, f.tipo, f.tienes, f.recom]));
  h += '<div class="fila" style="margin-top:8px">' + gbtn("Tomar fotos con la camara", 'data-g="capturar"', actual && (t.siguiente || {}).quien === "host") +
    gbtn("Subir fotos nuevas a Label Studio" + (tienes > tareas ? " (" + (tienes - tareas) + ")" : ""), 'data-g="sincronizar"', tienes > tareas) + "</div>" +
    '<p class="chico">La camara abre una ventana en el escritorio: usa sus teclas para capturar o salir.</p>';
  return h;
};
function gPre(t, actual, hijo) {
  const g = t.siguiente || {}, ls = t.ls || {};
  if (!actual) return "<p>Pre-etiquetado hecho" + (hijo ? " con el modelo hijo." : " con SAM 3.") + "</p>";
  if (g.quien === "espera") return '<p class="gespera">' + esc(g.texto) + ".</p>" + gAutoNota();
  if ((g.accion || {}).accion === "lote-importar") return "<p>Las predicciones ya llegaron.</p>" + gbtn("Subirlas a Label Studio", 'data-g="accion"', true);
  const n = ((g.accion || {}).opciones || {})["--muestra"] || 30;
  return hijo
    ? "<p>El modelo hijo va a pre-etiquetar las <b>" + n + "</b> fotos que faltan; tu solo corriges.</p>" + gbtn("Pre-etiquetar con el hijo", 'data-g="accion"', true)
    : "<p>SAM 3 dibuja una primera version en una muestra de fotos (" + (ls.task_number || 0) + " en total). Tu la corriges en el paso siguiente.</p>" +
      '<div class="fila"><label>Fotos de la muestra <input id="gmuestra" type="number" min="5" max="' + (ls.task_number || 500) + '" value="' + n + '"></label>' +
      gbtn("Pre-etiquetar con SAM 3", 'data-g="accion"', true) + "</div>";
}
PASO[4] = (t, a) => gPre(t, a, false);
PASO[7] = (t, a) => gPre(t, a, true);
function gVer(t, actual, final) {
  const ls = t.ls || {}, g = t.siguiente || {}, anot = ls.num_tasks_with_annotations || 0;
  if (!actual) return "<p>Revision hecha: " + anot + " fotos revisadas.</p>";
  const lsurl = esc(LS_URL) + "/projects/" + t.n + "/";
  return "<p>Abre Label Studio, revisa cada foto, corrige lo que este mal (un clic sobre un objeto lo marca con SAM 3) y da <b>Submit</b>.</p>" +
    gbarra(anot, ls.task_number || 0) + '<div class="fila" style="margin-top:8px"><a href="' + lsurl + '" target="_blank" rel="noopener">' +
    gbtn("Abrir Label Studio", 'data-fijo="1"', true) + "</a>" +
    (g.accion ? gbtn(final ? "Ya revise: entrenar el modelo final" : "Ya revise la muestra: entrenar el modelo hijo", 'data-g="accion"') : "") + "</div>" +
    (g.accion ? "" : '<p class="chico">Revisa al menos una foto para poder entrenar.</p>');
}
PASO[5] = (t, a) => gVer(t, a, false);
PASO[8] = (t, a) => gVer(t, a, true);
function gModelo(t, actual, final) {
  const g = t.siguiente || {}, m = t.modelos || {};
  if (!actual) return "<p>Modelo " + (final ? "final" : "hijo") + " listo" + (m.activo ? ": <b>" + esc(m.activo) + "</b>" : "") + ".</p>";
  if (g.quien === "espera") return '<p class="gespera">' + esc(g.texto) + " (de 10 a 30 min).</p>" + gAutoNota();
  if ((g.accion || {}).accion === "registrar") return "<p>El entrenamiento termino. Registra el modelo para usarlo.</p>" + gbtn("Registrar y activar", 'data-g="accion"', true);
  return "<p>Se exportan las fotos revisadas y se entrena en Kaggle.</p>" + gbtn("Entrenar", 'data-g="accion"', true);
}
PASO[6] = (t, a) => gModelo(t, a, false);
PASO[9] = (t, a) => gModelo(t, a, true);
PASO[10] = t => "<p>Abre la camara con el modelo activo y mira el conteo en vivo.</p>" + '<div class="fila">' +
  gbtn("Probar en vivo", 'data-g="ver"', true) + gbtn("Medir aceptacion", 'data-g="aceptacion"') + "</div>" +
  '<p class="chico">La camara abre una ventana en el escritorio; ciérrala con su tecla de salida o con Cancelar.</p>';
function gAutoNota() {
  return DAEMON.activo ? '<p class="chico">El automatico lo trae solo; esta vista se actualiza sola.</p>'
    : '<p class="chico">Enciende el <b>Automatico</b> (arriba) para que se envie y se traiga solo.</p>';
}

function gPanel() {
  const t = gtar(), p = GNUEVO ? 1 : gpaso(t), v = Math.min(GVER || p, p);
  if (!GNUEVO && !t) { G("gtitulo").textContent = "Elige un proyecto o crea uno nuevo"; G("gpasos").innerHTML = ""; G("gcont").innerHTML = ""; return; }
  G("gtitulo").textContent = GNUEVO ? "Nuevo proyecto" : t.titulo;
  gPasos(t);
  const f = PASO[v];
  G("gcont").innerHTML = '<h3 class="gfase">Paso ' + v + " de " + FASES.length + ": " + esc(FASES[v - 1]) + "</h3>" +
    (f ? f(t, v === p) : "") + (v < p && !GNUEVO ? '<p class="chico"><a href="#" data-gver="' + p + '">Ir al paso actual</a></p>' : "");
  if (G("gnombre")) {
    const nom = () => { GNOMBRE = G("gnombre").value; const s = gslug(GNOMBRE); G("gslugv").textContent = s ? "Nombre corto: " + s : ""; };
    G("gnombre").oninput = nom; nom();
  }
  if (G("gaudio") && GBLOB) G("gaudio").src = URL.createObjectURL(GBLOB);
  gTrabajo();
  clearTimeout(GPOLL);
  if (t && ((t.siguiente || {}).quien === "espera" || ((t.asistente || {}).ultimo === "pendiente"))) GPOLL = setTimeout(cargarProyectos, 15000);
}
function pintarGuiado() {
  if (!G("vguiado")) return;
  if (!GNUEVO && GSEL && !gtar()) GSEL = null;
  if (!GNUEVO && !GSEL && gcasos().length) GSEL = gcasos()[0].slug;
  gEstado(); gLista();
  const activo = document.activeElement;           // no borrar lo que la persona esta escribiendo
  if (activo && G("gcont").contains(activo) && /^(TEXTAREA|INPUT)$/.test(activo.tagName) && activo.value) return;
  gPanel();
}
async function gDetalle(slug) {
  try { GDET[slug] = await api("/api/asistente?slug=" + encodeURIComponent(slug)); } catch (e) { GDET[slug] = {error: e.message}; }
  if (slug === GSEL) gPanel();
}

// ---- trabajo en curso y confirmacion (sin re-pintar el paso)
function gTrabajo() {
  const t = TRAB || {}, ocupado = !!t.corriendo;
  document.querySelectorAll("#vguiado .gbtn").forEach(b => { if (!b.dataset.fijo) b.disabled = ocupado || b.hasAttribute("data-off"); });
  const c = G("gconf");
  const pend = PENDIENTE && t.id === PENDIENTE.id && !t.corriendo && t.rc === 0;
  const dmn = GDAEMON && t.id === GDAEMON && !t.corriendo && t.rc === 0;
  if (pend || dmn) {
    G("gconftxt").textContent = dmn ? "La prueba del automatico salio bien. Lo enciendo? Enviara y traera de Kaggle sin preguntar."
      : "Revisa el reporte en la consola. Si esta bien, confirma para hacerlo.";
    c.style.display = "block";
  } else c.style.display = "none";
  if (t.id && !t.corriendo && t.rc && t.rc !== 0 && (PENDIENTE || GDAEMON)) GDAEMON = 0;
}
function gHacer(ab) { GDAEMON = 0; correrAccion(ab, false); G("csalida").scrollIntoView({behavior: "smooth", block: "nearest"}); }
function gAccion(t, extra) {
  const a = (t.siguiente || {}).accion;
  if (!a) return;
  gHacer({accion: a.accion, slug: a.slug || null, n: a.n || null, opciones: Object.assign({}, DEFECTOS[a.accion] || {}, a.opciones || {}, extra || {})});
}

// ---- grabadora del paso 2
async function gGrabar() {
  if (GREC) { GREC.stop(); return; }
  let st;
  try { st = await navigator.mediaDevices.getUserMedia({audio: true}); } catch (e) { alert("Sin acceso al microfono: " + e.message); return; }
  const tipos = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  const tipo = tipos.find(x => window.MediaRecorder && MediaRecorder.isTypeSupported(x)) || "", partes = [];
  GREC = new MediaRecorder(st, tipo ? {mimeType: tipo} : {});
  GREC.ondataavailable = e => { if (e.data.size) partes.push(e.data); };
  GREC.onstop = () => {
    st.getTracks().forEach(x => x.stop());
    const mt = GREC.mimeType || tipo;
    GEXT = mt.includes("ogg") ? ".ogg" : mt.includes("mp4") ? ".mp4" : ".webm";
    GBLOB = new Blob(partes, {type: mt}); GREC = null; clearInterval(GTREC); gPanel();
  };
  GREC.start(); GT0 = Date.now(); gPanel();
  GTREC = setInterval(() => { if (G("grecinfo")) G("grecinfo").textContent = "Grabando... " + Math.round((Date.now() - GT0) / 1000) + " s"; }, 500);
}
async function gEnviar(t, continuar) {
  const d = {slug: t.slug, nuevo: !t.spec, continuar: !!continuar};
  try {
    if (continuar) d.respuestas = (G("gresp") || {}).value || "";
    else if (GMODO === "escribir") d.texto = (G("gtexto") || {}).value || "";
    else {
      if (!GBLOB) { alert("Graba primero tu descripcion (o cambia a Escribir)."); return; }
      const r = await fetch("/api/audio", {method: "POST", headers: {"X-XD": "1", "X-Slug": t.slug, "X-Ext": GEXT}, body: GBLOB});
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      d.audio = j.audio;
    }
    await api("/api/asistente", d);
  } catch (e) { alert(e.message); return; }
  GBLOB = null; delete GDET[t.slug]; PENDIENTE = null; sondear();
}

// ---- clics
G("vguiado").addEventListener("click", async e => {
  const b = e.target.closest("[data-g],[data-gsel],[data-gver],[data-gmodo]");
  if (!b) return;
  if (b.tagName === "A") e.preventDefault();
  const t = gtar(), q = b.dataset.g;
  if (b.dataset.gsel) { GSEL = b.dataset.gsel; GNUEVO = false; GVER = null; gguardar(); return pintarGuiado(); }
  if (b.dataset.gver) { GVER = +b.dataset.gver; return gPanel(); }
  if (b.dataset.gmodo) { GMODO = b.dataset.gmodo; return gPanel(); }
  if (q === "nuevo") { GNUEVO = true; GVER = null; gLista(); return gPanel(); }
  if (q === "crear") {
    const nombre = (G("gnombre").value || "").trim(), slug = gslug(nombre);
    if (!slug) { alert("Escribe un nombre para el proyecto."); return; }
    if (ULTIMO.some(x => x.slug === slug)) { alert("Ya existe un proyecto con ese nombre corto (" + slug + ")."); return; }
    GSEL = slug; gguardar();
    return gHacer({accion: "caso-nuevo", slug: slug, n: null, opciones: {"--titulo": nombre}});
  }
  if (q === "auto-on") {                          // reporte de un ciclo y, si sale bien, se pide confirmar
    PENDIENTE = null;
    try { GDAEMON = (await api("/api/accion", {accion: "daemon", opciones: {"--una-vez": true}})).id; } catch (err) { alert(err.message); }
    return sondear();
  }
  if (q === "auto-off") { try { DAEMON = await api("/api/daemon", {op: "parar"}); } catch (err) { alert(err.message); } return cargarServicios(); }
  if (!t) return;
  if (q === "accion") {
    const extra = G("gmuestra") ? {"--muestra": G("gmuestra").value} : null;
    return gAccion(t, extra);
  }
  if (q === "grabar") return gGrabar();
  if (q === "enviar") return gEnviar(t, false);
  if (q === "corregir") return gEnviar(t, true);
  if (q === "aplicar") return gHacer({accion: "asistente-importar", slug: t.slug, n: null, opciones: {"--forzar": !!(GDET[t.slug] || {}).spec_existe}});
  if (q === "plantilla") return gHacer({accion: "spec-nueva", slug: t.slug, n: null, opciones: {"--titulo": t.titulo}});
  if (q === "capturar") return gHacer({accion: "capturar", slug: t.slug, n: null, opciones: {}});
  if (q === "sincronizar") return gHacer({accion: "sincronizar", slug: t.slug, n: null, opciones: {}});
  if (q === "ver") return gHacer({accion: "ver", slug: null, n: t.n, opciones: {}});
  if (q === "aceptacion") return gHacer({accion: "aceptacion", slug: null, n: t.n, opciones: {}});
});
G("gconfsi").onclick = async () => {
  if (GDAEMON && TRAB.id === GDAEMON) {
    GDAEMON = 0; G("gconf").style.display = "none";
    try { DAEMON = await api("/api/daemon", {op: "iniciar", intervalo: 1}); } catch (e) { alert(e.message); }
    return cargarServicios();
  }
  if (PENDIENTE) { if (PENDIENTE.accion === "caso-nuevo") GNOMBRE = ""; GNUEVO = false; GVER = null; correrAccion(PENDIENTE, true); }
};
G("gconfno").onclick = () => { PENDIENTE = null; GDAEMON = 0; G("gconf").style.display = "none"; ocultarConfirmar(); };
