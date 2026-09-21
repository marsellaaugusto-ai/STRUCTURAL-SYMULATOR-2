"""Assemble the domain note. Run: python3 build.py ../../SHELL_DOMAIN_NOTE_2026-09-21.html"""
import sys, math
import figs

ELL = lambda x, y: (x / 0.86) ** 2 + (y / 0.72) ** 2 < 1.0

F_CUT, KEPT, TOT = figs.ellipse_cut()
F_GHOST = figs.ghost_cut()
F_TRIM = figs.trimmed_cut() + '\n' + figs.staircase_outline()
F_FIT = figs.fitted_cut()
SADDLE = lambda x, y: 0.42 * (x * x - y * y)
F_ISO_TRIM = figs.hypar_iso(rule=ELL, ghost=False, zfun=SADDLE,
                            trim=figs.snap_to_ellipse(0.86, 0.72, 0.09))

HEAD = r'''<title>Cutting the Hypar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root{
  --paper:#F3F6F8; --surface:#FFFFFF; --ink:#14181D; --muted:#5C6874;
  --line:#D6DDE4; --line-hard:#B6C2CD;
  --blue:#1F5C8B; --blue-soft:#E1ECF4; --blue-tint:#CBDFEE;
  --red:#B4322A;  --red-soft:#F7E5E2;
  --amber:#946808; --amber-soft:#F8EEDA;
  --green:#2C6E5B; --green-soft:#E1EDE8;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#11151A; --surface:#191F26; --ink:#E6ECF2; --muted:#98A4B0;
  --line:#2B343D; --line-hard:#3D4954;
  --blue:#74B3E0; --blue-soft:#15303F; --blue-tint:#1D3F55;
  --red:#E8867C;  --red-soft:#3A2220;
  --amber:#DEB25E;--amber-soft:#342A18;
  --green:#71C1A6;--green-soft:#16302A;
}}
:root[data-theme="dark"]{
  --paper:#11151A; --surface:#191F26; --ink:#E6ECF2; --muted:#98A4B0;
  --line:#2B343D; --line-hard:#3D4954;
  --blue:#74B3E0; --blue-soft:#15303F; --blue-tint:#1D3F55;
  --red:#E8867C;  --red-soft:#3A2220;
  --amber:#DEB25E;--amber-soft:#342A18;
  --green:#71C1A6;--green-soft:#16302A;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);
     font-family:"Source Serif 4",Georgia,serif;font-size:17px;line-height:1.62;
     padding-block:0 72px;margin:0}
.wrap{max-width:1020px;margin-inline:auto;padding-inline:20px}
.prose{max-width:68ch}
h1,h2,h3,h4,.label,.eyebrow,th,.btn{font-family:Archivo,"Helvetica Neue",Arial,sans-serif}
h1{font-size:clamp(2rem,5vw,3.1rem);line-height:1.04;font-weight:700;letter-spacing:-.02em;
   text-wrap:balance;margin:0 0 .35em}
h2{font-size:clamp(1.35rem,3vw,1.75rem);font-weight:600;letter-spacing:-.01em;
   text-wrap:balance;margin:0 0 .5em}
h3{font-size:1.08rem;font-weight:600;margin:1.8em 0 .4em;text-wrap:balance}
p{margin:0 0 1em}
a{color:var(--blue)}
code,.mono{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.86em}
code{background:var(--blue-soft);padding:.12em .38em;border-radius:3px;
     color:var(--ink);white-space:nowrap}
header.top{border-bottom:1px solid var(--line-hard);padding-block:56px 30px;margin-bottom:44px}
.eyebrow{font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;color:var(--blue);
         font-weight:600;margin:0 0 1.1em}
.stand{font-size:1.16rem;color:var(--muted);max-width:60ch;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:22px;font-family:Archivo,sans-serif;
      font-size:.78rem;color:var(--muted);letter-spacing:.02em}
section{padding-block:34px 10px;border-top:1px solid var(--line);margin-top:34px}
section:first-of-type{border-top:0;margin-top:0}
.qnum{font-family:Archivo,sans-serif;font-size:.74rem;letter-spacing:.14em;
      text-transform:uppercase;color:var(--muted);font-weight:600;display:block;margin-bottom:.5em}
/* verdict strip */
.verdict{display:flex;gap:14px;align-items:flex-start;border-left:3px solid var(--line-hard);
         padding:12px 0 12px 16px;margin:0 0 24px;max-width:68ch}
.verdict.yes{border-color:var(--green)}
.verdict.part{border-color:var(--amber)}
.verdict.no{border-color:var(--red)}
.verdict .tag{font-family:Archivo,sans-serif;font-size:.7rem;letter-spacing:.1em;
      text-transform:uppercase;font-weight:700;padding:3px 8px;border-radius:3px;white-space:nowrap;
      margin-top:3px}
.verdict.yes .tag{background:var(--green-soft);color:var(--green)}
.verdict.part .tag{background:var(--amber-soft);color:var(--amber)}
.verdict.no .tag{background:var(--red-soft);color:var(--red)}
.verdict p{margin:0}
/* figures */
figure{margin:30px 0;background:var(--surface);border:1px solid var(--line);
       border-radius:5px;padding:20px 18px 14px}
figure svg{display:block;width:100%;height:auto;max-width:100%}
figure img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:3px}
figcaption{font-size:.87rem;color:var(--muted);margin-top:14px;line-height:1.5;max-width:76ch}
figcaption b{color:var(--ink);font-weight:600}
.panels{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.panel .label{font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;font-weight:700;
              color:var(--muted);margin:0 0 8px;display:block}
.panel .sub{font-size:.82rem;color:var(--muted);margin:8px 0 0;font-family:"Source Serif 4",serif}
/* svg element classes */
.cell-in{fill:var(--blue-tint);stroke:var(--line-hard);stroke-width:.6}
.cell-out{fill:none;stroke:var(--line);stroke-width:.5;stroke-dasharray:2 2}
.cell-ghost{fill:var(--line-hard);opacity:.22;stroke:var(--line);stroke-width:.4}
.stair{stroke:var(--amber);stroke-width:1.6;stroke-dasharray:4 3;fill:none}
.curve{fill:none;stroke:var(--red);stroke-width:2;stroke-linejoin:round}
.band{fill:none;stroke:var(--amber);stroke-width:1;stroke-dasharray:3 3}
.dot-in{fill:var(--blue)}
.dot-out{fill:var(--muted);opacity:.45}
.face{fill:var(--blue-soft);stroke:var(--blue);stroke-width:.5;stroke-linejoin:round}
.face-ghost{fill:var(--line);opacity:.35;stroke:none}
.ruling{stroke:var(--red);stroke-width:.9;opacity:.75}
.sv-ink{fill:var(--ink)} .sv-mut{fill:var(--muted)}
.sv-line{stroke:var(--line-hard);fill:none;stroke-width:1}
.sv-beam{stroke:var(--blue);stroke-width:4;fill:none;stroke-linecap:round}
.sv-red{stroke:var(--red);stroke-width:2;fill:none}
.sv-t{font-family:Archivo,sans-serif;font-size:11px;fill:var(--muted)}
.sv-t.b{fill:var(--ink);font-weight:600}
/* tables */
.tbl{width:100%;border-collapse:collapse;font-size:.9rem;margin:22px 0;
     font-family:"Source Serif 4",serif}
.tbl th{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;text-align:left;
        color:var(--muted);font-weight:700;padding:0 12px 8px 0;border-bottom:1px solid var(--line-hard)}
.tbl td{padding:9px 12px 9px 0;border-bottom:1px solid var(--line);vertical-align:top}
.tbl td.num{font-family:"JetBrains Mono",monospace;font-size:.84rem;font-variant-numeric:tabular-nums;
            white-space:nowrap}
.scroll{overflow-x:auto}
/* callouts */
.note{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--blue);
      border-radius:0 4px 4px 0;padding:16px 18px;margin:24px 0;max-width:72ch}
.note.warn{border-left-color:var(--amber)}
.note.stop{border-left-color:var(--red)}
.note p:last-child{margin-bottom:0}
.note .label{display:block;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;
             font-weight:700;color:var(--blue);margin-bottom:.5em}
.note.warn .label{color:var(--amber)} .note.stop .label{color:var(--red)}
/* question list */
ol.qs{list-style:none;counter-reset:q;padding:0;margin:26px 0 0}
ol.qs>li{counter-increment:q;background:var(--surface);border:1px solid var(--line);
         border-radius:5px;padding:20px 20px 16px;margin-bottom:14px;position:relative}
ol.qs>li::before{content:counter(q,upper-alpha);position:absolute;left:-13px;top:18px;
  width:26px;height:26px;border-radius:50%;background:var(--blue);color:var(--paper);
  font-family:Archivo,sans-serif;font-weight:700;font-size:.8rem;display:grid;place-items:center}
@media(max-width:560px){ol.qs>li::before{position:static;margin-bottom:10px}}
ol.qs h3{margin:0 0 .5em}
ol.qs .opts{margin:.6em 0 0;padding-left:1.1em}
ol.qs .opts li{margin-bottom:.35em}
.default{font-size:.88rem;color:var(--muted);border-top:1px dashed var(--line-hard);
         margin-top:14px;padding-top:10px}
.default b{color:var(--ink);font-weight:600}
ul.tight{padding-left:1.15em;margin:0 0 1em}
ul.tight li{margin-bottom:.4em}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 18px;font-size:.9rem;margin:18px 0}
.kv dt{font-family:Archivo,sans-serif;font-size:.74rem;letter-spacing:.06em;text-transform:uppercase;
       color:var(--muted);font-weight:600;padding-top:3px}
.kv dd{margin:0}
hr.soft{border:0;border-top:1px solid var(--line);margin:34px 0}
.formula{font-family:"JetBrains Mono",monospace;font-size:.92rem;background:var(--surface);
         border:1px solid var(--line);border-radius:4px;padding:12px 14px;margin:16px 0;
         overflow-x:auto;white-space:pre}
</style>'''

BODY_1 = r'''
<div class="wrap">
<header class="top">
  <p class="eyebrow">Shell (RC) — understanding note, before any code</p>
  <h1>Cutting the Hypar</h1>
  <p class="stand">You asked six things. Here is each one back in my words, with a picture,
  plus what I measured in the running tab and the questions I will not answer for you
  by guessing.</p>
  <div class="meta">
    <span>21 Sep 2026</span><span>branch <code>claude/shell-rc-rebuild</code></span>
    <span>nothing built yet</span><span>TP 2 Paraboloide Hiperbólico read</span>
  </div>
</header>

<section>
<span class="qnum">The six answers in one page</span>
<h2>Short answers first</h2>
<div class="scroll"><table class="tbl">
<thead><tr><th style="width:30%">You asked</th><th style="width:12%">Today</th><th>The short answer</th></tr></thead>
<tbody>
<tr><td><b>1.</b> An elliptical piece of a hypar?</td><td><b style="color:var(--green)">Yes</b></td>
    <td>One line in <code>keep where</code>: <code>(2x/a)^2 + (2y/b)^2 &lt; 1</code>. I ran it — picture below.</td></tr>
<tr><td><b>2.</b> How does the slicing work?</td><td><b style="color:var(--red)">It doesn't</b></td>
    <td>Nothing is sliced. Each element is judged <em>at its centre</em> and kept or dropped whole. That is the staircase you are seeing.</td></tr>
<tr><td><b>3.</b> A card: most tension, most compression, the governing element</td><td><b style="color:var(--amber)">Data exists</b></td>
    <td>The numbers are already computed every run; nothing shows them as a card. One word of yours I cannot pin down — "the sliced element".</td></tr>
<tr><td><b>4.</b> Fade the elements outside the boundary</td><td><b style="color:var(--red)">No</b></td>
    <td>Understood — but I would rather <em>cut</em> them than fade them, and I want to show you why before I build either.</td></tr>
<tr><td><b>5.</b> Can you build the TP 2 structures?</td><td><b style="color:var(--amber)">Mostly</b></td>
    <td>I built your 9 × 9 module and the app reproduces your hand calculation. Three things it cannot do yet — listed, with numbers.</td></tr>
<tr><td><b>6.</b> Surface <code>f(x,y)</code> + contour <code>g</code></td><td><b style="color:var(--blue)">Your idea</b></td>
    <td>I read it as one signed expression <code>g(x,y) ≤ 0</code>. It is the piece that makes 2 and 4 solvable instead of patched.</td></tr>
</tbody></table></div>
</section>

<section>
<span class="qnum">Question 1</span>
<h2>Yes — the elliptical domain already works</h2>
<div class="verdict yes"><span class="tag">Works today</span>
<p>The <b>Surface</b> panel has a <code>keep where</code> box. Any true/false expression in
<code>x</code> and <code>y</code> can go in it, using every number you have defined.
An ellipse is one line. I typed it into the running tab and analysed it — this is that run,
not a drawing.</p></div>

<div class="prose">
<p>The shapes in your reference picture, in the language the box already speaks:</p>
</div>

<div class="scroll"><table class="tbl">
<thead><tr><th style="width:34%">Shape</th><th>Type this into <code>keep where</code></th></tr></thead>
<tbody>
<tr><td>Elliptical disc (your picture)</td><td class="num">(2x/a)^2 + (2y/b)^2 &lt; 1</td></tr>
<tr><td>Circular disc</td><td class="num">hypot(x, y) &lt; min(a, b)/2</td></tr>
<tr><td>Elliptical ring</td><td class="num">0.4 &lt; hypot(2x/a, 2y/b) &lt; 1</td></tr>
<tr><td>Angular sector, 0° to 90°</td><td class="num">hypot(x, y) &lt; r and x &gt; 0 and y &gt; 0</td></tr>
<tr><td>Your TP 2 <i>sector bajo paraboloide</i> (cut on the diagonal)</td><td class="num">y &lt; x</td></tr>
<tr><td>Between the asymptotes and a hyperbola</td><td class="num">x y &lt; c and x &gt; 0 and y &gt; 0</td></tr>
<tr><td>L-shaped plan</td><td class="num">not (x &gt; 0 and y &gt; 0)</td></tr>
</tbody></table></div>

<figure>
  <img src="shell_domain_figures/today_ellipse_top.png" alt="The Shell tab in plan view, showing an elliptical
  cut out of a 12 by 12 m hypar. The kept elements form a stair-stepped disc; the edge beams
  and the four support markers are still on the original rectangle.">
  <figcaption><b>The real tab, this morning.</b> Hypar preset, 12 × 12 m, 0.5 m elements,
  <code>(2x/a)^2 + (2y/b)^2 &lt; 1</code>, analysed. 128 of 576 elements removed, 448 left.
  Two things to look at, and only one of them is the one you mentioned: the <b>staircase</b>
  on the edge, and the fact that the <b>purple edge beams and the four support triangles are
  still sitting on the rectangle</b> — not on the ellipse.</figcaption>
</figure>
</section>

<section>
<span class="qnum">Question 2</span>
<h2>How the "slicing" works: it doesn't slice</h2>
<div class="verdict no"><span class="tag">Nothing is cut</span>
<p>There is no slicing anywhere in the code. The mesh is built over the full rectangle, then
every element is tested <b>once, at its centre point</b>. In or out. Whole.</p></div>

<figure>
  <div style="max-width:420px;margin-inline:auto">
  <svg viewBox="0 0 248 248" role="img" aria-label="A 12 by 12 grid with an ellipse drawn
  over it. Each cell carries a dot at its centre; cells whose dot falls inside the ellipse
  are filled, the others are left as dashed outlines. Two dashed amber curves show the
  half-element band the decision can overshoot by.">
  __FIG_CUT__
  </svg></div>
  <figcaption><b>The centre test, drawn by the same rule the code uses.</b>
  Filled: the dot is inside, the element is kept whole — including the part of it that
  sticks out past the red curve. Dashed: dropped whole, including the part of it that was
  inside. The amber band is the <b>± half an element</b> the answer can be wrong by.
  Refine the mesh and the band narrows; the staircase never stops being a staircase.</figcaption>
</figure>

<div class="prose">
<p>Two consequences, and the second is the one that matters:</p>
<ul class="tight">
<li><b>The area converges.</b> In the run above the kept elements cover 112.0 m² against
the ellipse's true 113.1 m² — 1.0 % light. Halve the elements and that error halves.</li>
<li><b>The perimeter does not.</b> The cut boundary in that run is 96 element edges at 0.5 m
= <b>48.0 m</b>. The true ellipse perimeter is 37.7 m. That is <b>27 % too long — and it stays
27 % too long however fine you make the mesh</b>, because a staircase approximating a diagonal
keeps its full taxicab length forever. An edge beam laid on that boundary would be a 27 %
too long, 27 % too heavy zigzag.</li>
</ul>
<p>So the jagged edge is not only ugly. It is the reason the cut boundary cannot yet carry a
beam or a support, which is the next picture.</p>
</div>
</section>

<section>
<span class="qnum">The part you did not ask about</span>
<h2>The cut has no edge</h2>
<div class="verdict no"><span class="tag">Changes results</span>
<p>When <code>keep where</code> removes elements, the edge beams and the supports stay
where they were: on the four sides and the four corners of the <b>original rectangle</b>.
I measured it — of the 25 nodes on each edge beam, only <b>7</b> still touch the shell.</p></div>

<figure>
<div class="panels">
  <div class="panel"><span class="label">Today</span>
  <svg viewBox="0 0 248 268" role="img" aria-label="Plan: a stair-stepped elliptical shell
  inside a square. The thick beams run along the square, and the supports sit at the square's
  four corners, far from the shell.">
    __FIG_TODAY_EDGE__
  </svg>
  <p class="sub">The shell touches the beam ring at four points. The load reaches the supports
  by bending the ring, which is not the structure you drew.</p></div>

  <div class="panel"><span class="label">What I think you want</span>
  <svg viewBox="0 0 248 268" role="img" aria-label="Plan: a smooth elliptical shell whose
  own boundary carries the edge beam, with supports placed on that boundary.">
    __FIG_WANT_EDGE__
  </svg>
  <p class="sub">The beam follows the <em>cut</em>, at its true length, and the supports are
  picked on the cut. This only becomes possible once the boundary is a curve, not a staircase.</p></div>
</div>
<figcaption><b>Why the domain job and the edge job are one job.</b> I would not ship the
smooth-looking ellipse while the beams and supports still belong to the rectangle — that
would be a picture of a structure the solver is not solving.</figcaption>
</figure>
</section>
'''

BODY_2 = r'''
<section>
<span class="qnum">Question 4</span>
<h2>Fading the outside, and why I would cut instead</h2>
<div class="prose">
<p>What I understood: the staircase distracts from the real geometry, and you would like the
elements past the boundary to be sliced, with everything outward of the slice made
transparent. Three different things can be done here and they are worth separating, because
one of them is a drawing change and one of them is a change to what gets solved.</p>
</div>

<figure>
<div class="panels">
  <div class="panel"><span class="label">A · Ghost the outside</span>
  <svg viewBox="0 0 248 248" role="img" aria-label="The full grid, with elements outside the
  ellipse drawn faintly and the ellipse curve drawn over them.">__FIG_GHOST__</svg>
  <p class="sub">Drawing only. The model still contains the whole staircase; the boundary is
  still a staircase. Honest use: showing the <em>parent</em> surface your piece was cut from —
  which is exactly what your reference picture shows.</p></div>

  <div class="panel"><span class="label">B · Trim the drawing</span>
  <svg viewBox="0 0 248 248" role="img" aria-label="The kept elements clipped exactly to the
  ellipse, giving a smooth edge.">__FIG_TRIM__</svg>
  <p class="sub">Looks right immediately, costs almost nothing. But the drawing is now smooth
  while the thing being solved is still the staircase — the amber dashes — a picture of a structure that was not
  analysed. I would only ship this with the mesh fitted as well.</p></div>

  <div class="panel"><span class="label">C · Fit the mesh</span>
  <svg viewBox="0 0 248 248" role="img" aria-label="The boundary nodes pulled onto the ellipse
  so the element edges follow the curve exactly, giving distorted but well-shaped quads at the
  edge.">__FIG_FIT__</svg>
  <p class="sub">The boundary <em>nodes</em> move onto the curve. The edge elements become
  slightly distorted quadrilaterals that follow it exactly. Now the drawing, the area, the
  perimeter, the edge beam and the supports all agree, because there is only one boundary.</p></div>
</div>
<figcaption><b>The same ellipse on the same 12 × 12 grid, three ways.</b> C is drawn by
projecting each boundary node onto the ellipse, exactly as the code would, and refusing the
move when it would be more than 55 % of an element — the guard that stops a node crossing its
neighbour and producing a sliver.</figcaption>
</figure>

<div class="note stop"><span class="label">One hard constraint you should know</span>
<p>The 3-D view is a Tk canvas. <b>Tk polygons have no alpha channel.</b> "Transparent" on
this canvas is either a coarse stipple pattern (visible dots) or a colour I blend against the
background myself. Blending looks far better and is what I would use — but it means a ghosted
element cannot show what is behind it, only that it is not part of the structure.</p></div>

<div class="note"><span class="label">My recommendation</span>
<p><b>C for the structure, A as a separate toggle.</b> Fit the mesh so the cut is a real
boundary — that fixes the staircase, the perimeter, the edge beam and the supports in one
move. Then add <em>"show the parent surface"</em> as its own checkbox, which ghosts the whole
uncut hypar behind your piece. That is the picture you sent me, and it is genuinely useful:
it shows where your sector sits on the surface and where the straight generators run off it.
Doing A <em>instead</em> of C would hide the staircase without removing it.</p></div>
</section>

<section>
<span class="qnum">Question 6</span>
<h2>Your contour idea, as I read it</h2>
<div class="prose">
<p>You wrote: <i>given a function surface f(x,y) we establish the domain in 3d, then we
establish the contour of the shape using an expression g(x)</i>. Here is that in my words,
and I want you to correct me if the second step is wrong.</p>
</div>

<figure>
<svg viewBox="0 0 900 250" role="img" aria-label="Three steps. First, the surface z = f(x,y)
drawn as a saddle over a square. Second, the same square in plan with a closed curve g = 0
drawn on it and the inside shaded. Third, the saddle trimmed to that curve, with the boundary
carrying an edge beam.">
__FIG_STEPS__
</svg>
<figcaption><b>Two independent definitions, composed.</b> <span style="color:var(--blue)">
<b>f</b></span> says what the surface is and never changes when you re-cut it.
<span style="color:var(--red)"><b>g</b></span> says where the shape ends, and never changes
when you reshape the surface. Today the app has f and a yes/no test; the missing piece is that
the test is not a <em>curve</em>, so nothing can be placed on it.</figcaption>
</figure>

<div class="prose">
<p>The change I would make is small to type and large in what it buys: instead of a
<em>condition</em>, the box takes a <em>signed expression</em>, and the shell is kept where it
is negative.</p>
</div>

<div class="formula">today    keep where   (2x/a)^2 + (2y/b)^2 &lt; 1      → a yes / no per element
proposed edge where   (2x/a)^2 + (2y/b)^2 - 1      → g &lt; 0 inside, g = 0 ON the edge, g &gt; 0 outside</div>

<div class="prose">
<p>That single change is what unlocks everything else on your list:</p>
<ul class="tight">
<li><b>g = 0 is a curve</b>, so the edge can be found exactly on every element it crosses
(the intersections along element edges, by interpolation) — that is the real "slice".</li>
<li><b>Nodes can be projected onto it</b> → the fitted mesh in panel C.</li>
<li><b>The edge beam can be laid along it</b> at its true length, instead of a 27 % too long zigzag.</li>
<li><b>Supports can be picked on it</b> — your corner-picking from Stage 4 works on the new corners.</li>
<li><b>The sign tells you inside from outside without a second expression</b>, so ghosting the
outside (option A) is free.</li>
<li><b>Presets become one line each</b>, and can be named: ellipse, disc, ring, sector,
the region under a hyperbola.</li>
</ul>
<p>I would keep the current <code>keep where</code> box working exactly as it does — it can
express things a single smooth g cannot (an L, a union of holes) — and treat <code>edge where</code>
as the better-behaved case that gets the trimming, the beam and the supports. Where you give
a g, you get a real edge; where you give a condition, you get today's staircase and a note
saying so.</p>
</div>

<div class="note warn"><span class="label">What I need you to confirm</span>
<p>You wrote <code>g(x)</code>, a function of x alone. That reads two ways.
<b>(i)</b> a closed contour in the plane, <code>g(x, y) = 0</code> — which is what the picture
above shows and what the ellipse needs; or <b>(ii)</b> a pair of bounding curves,
<code>y1(x) ≤ y ≤ y2(x)</code>, which is how you would write "the region between two parabolas"
and is easier to type for a shape that is a band. (ii) cannot express a ring, and (i) cannot
express "different left and right ends" as directly. Question E at the end asks which.</p></div>
</section>
'''

BODY_3 = r'''
<section>
<span class="qnum">Question 3</span>
<h2>The card: which element decides the design</h2>
<div class="verdict part"><span class="tag">Numbers exist, card does not</span>
<p>Every run already works out the principal membrane forces per element, the utilisation of
seven separate checks, and which check governs. It is all in the report text at the bottom.
Nothing puts it where your eye is — the left rail.</p></div>

<figure>
<div style="max-width:430px;margin-inline:auto">
<svg viewBox="0 0 400 356" role="img" aria-label="A mock-up of a card in the left rail with
three rows: most tension, most compression, and the governing element, each showing the
element number, its position, a value and the governing check.">
__FIG_CARD__
</svg></div>
<figcaption><b>Mock-up, with real numbers</b> from your TP 2 module rebuilt in the tab
(9 × 9 m, k = 0.0538, t = 8 cm, 1.2D + 1.6L<sub>r</sub>). Each row would be clickable: click
it and the model turns to that element, selects it, and opens a section through it.</figcaption>
</figure>

<div class="prose">
<p>Notice what those real numbers say: all three worst elements are in the corner, on the
support. That is the support singularity, not the shell — which is why I would put
<b>two</b> numbers in each row: the worst anywhere, and the worst away from the support
blocks. Otherwise the card will tell you "the corner" every single time and teach you nothing
about the shell.</p>

<h3>The one word I cannot pin down: "the sliced element"</h3>
<p>You wrote: <i>the element that is suffering the most tension and the most compression and
the sliced element … the element at maximum capacity that determines how the structure is
going to be calculated.</i> The second half of that sentence is clear — the governing element,
the one at highest utilisation. "The sliced element" could be three things and they are all
worth having:</p>
<ul class="tight">
<li><b>The same as the governing element</b>, described from a different angle — then it is
one row, not two.</li>
<li><b>The element the current section cut passes through</b> — so the Sections panel and the
card talk to each other.</li>
<li><b>The 1 m design strip</b> — <i>"corresponde a una franja del paraboloide de 1 m de ancho"</i>,
in your own words on the poster. That is a different and very useful thing, and I would like
to build it whether or not it is what you meant. See below.</li>
</ul>
</div>

<div class="note"><span class="label">A fourth thing I would add: your strip, computed</span>
<p>Your poster designs by taking a 1 m wide strip along a generating parabola and running
<code>H = q'L²/8f</code>, then <code>σ = H/(e·100)</code> and <code>Fe = H/σ<sub>e</sub></code>.
The app could draw that strip on the model and print your three numbers beside its own finite
element numbers, for the same strip. Then you can defend one with the other in a jury, instead
of hoping they agree. I checked: on your module they agree — the next section has it.</p></div>
</section>

<section>
<span class="qnum">Question 5</span>
<h2>Can you build the TP 2 structures today?</h2>
<div class="verdict part"><span class="tag">Mostly — I built one</span>
<p>I rebuilt the 9 × 9 m module from your poster in the tab and analysed it. The geometry goes
in exactly; the membrane result matches your hand calculation; the 6 cm fails for a reason
your calculation could not see. Three things you cannot build yet.</p></div>

<div class="prose">
<h3>Your geometry goes in exactly</h3>
<p>Your generating parabola: span 9√2 = 12.72 m, rise f = 1.09 m. A hypar
<code>z = k·x·y</code> gives that when k = 0.0538 m⁻¹. I typed
<code>c = 4.36</code>, <code>z(x,y) = c·x·y/(a·b)</code> with a = b = 9 and asked the tab what
surface it had built. It answered <code>k = 0.053827</code>, and the parabola it implies has a
rise of 1.088 m over 12.72 m. Your number, to three figures.</p>

<h3>The finite element model agrees with your hand calculation</h3>
</div>

<div class="scroll"><table class="tbl">
<thead><tr><th>Quantity</th><th>Your poster</th><th>The tab (MITC4, 576 elements)</th><th>Verdict</th></tr></thead>
<tbody>
<tr><td>Service load q</td><td class="num">250 kg/m²</td><td class="num">2.24 kN/m² = 228 kg/m²</td>
    <td>self weight at 24 kN/m³ + 20 + 60</td></tr>
<tr><td>Membrane shear in the field, q/2k</td><td class="num">2 319 kg/m = 22.7 kN/m</td>
    <td class="num">19.2 – 27.8 kN/m</td><td><b style="color:var(--green)">Agrees</b></td></tr>
<tr><td>Principal tension N₁</td><td class="num">= H = 22.7 kN/m</td><td class="num">12.5 – 30.7 kN/m</td>
    <td>same order, varies over the field</td></tr>
<tr><td>Principal compression N₂</td><td class="num">= −H</td><td class="num">−22.1 – −37.0 kN/m</td>
    <td>higher near the low corners</td></tr>
<tr><td>Bending in the field</td><td class="num">assumed zero</td><td class="num">≤ 0.19 kNm/m</td>
    <td>your assumption is sound</td></tr>
<tr><td>Deflection</td><td class="num">not checked</td><td class="num">4.4 mm long-term vs 36 mm limit</td>
    <td>comfortable</td></tr>
</tbody></table></div>

<div class="prose">
<p>That is the useful result of this whole exercise: <b>your membrane hand method is right for
this shell</b>, and now you have a model that says so with its own numbers.</p>

<h3>Where 6 cm fails — and it is not where you would expect</h3>
</div>

<div class="scroll"><table class="tbl">
<thead><tr><th>Check at t = 6 cm</th><th style="width:18%">Utilisation</th><th>Reading</th></tr></thead>
<tbody>
<tr><td>Concrete compression in the shell</td><td class="num">0.23</td><td>fine</td></tr>
<tr><td>Bending with one central mesh</td><td class="num">0.10</td><td>fine</td></tr>
<tr><td>Transverse shear, no stirrups</td><td class="num">0.41</td><td>fine</td></tr>
<tr><td>Shell buckling</td><td class="num">0.22</td><td>fine</td></tr>
<tr><td>Reinforcement fits (bars ≥ 75 mm apart)</td><td class="num">0.14</td><td>fine</td></tr>
<tr><td><b>Room for the mesh and the cover</b></td><td class="num" style="color:var(--red)"><b>1.43</b></td>
    <td><b>fails.</b> CIRSOC wants 35 mm cover on an exposed shell. 35 + 8 + 35 does not fit in
    60 mm. The detailing minimum is <b>8.6 cm</b> with one central mesh.</td></tr>
<tr><td><b>Shear into the support block</b></td><td class="num" style="color:var(--red)"><b>2.78</b></td>
    <td><b>fails.</b> The support is too small; punching governs. Widen the block, or
    thicken locally.</td></tr>
</tbody></table></div>

<div class="note warn"><span class="label">What this means for your poster</span>
<p>Structurally your 6 cm shell is not working hard — nothing in the shell itself is above
half capacity. It fails on <b>cover</b>, which the membrane method has no way to see, and on
<b>the support detail</b>, which the membrane method also has no way to see. Two honest routes:
go to 8.6 cm and keep 35 mm cover; or keep 6 cm and argue a lower cover class (a protected or
precast surface), which the tab lets you set and will then re-check. Either way the shell
itself is fine — which is worth knowing, and is the opposite of the conclusion a failed
utilisation bar usually suggests.</p></div>

<div class="prose">
<h3>Three things you cannot build yet</h3>
<ul class="tight">
<li><b>The 55 × 18 m assembly.</b> The tab meshes <em>one</em> f(x,y) over <em>one</em>
rectangle. Your big figure is several hypar tiles at different orientations meeting along
ridges and valleys. Some of these can be written as a single formula —
the inverted umbrella preset already is, using <code>abs(x)</code> — but a general assembly of
tiles is a genuine change to the model, and the largest single item on this page.</li>
<li><b>The tie between the low points.</b> Your poster resolves the horizontal thrust
<code>H</code> with a tie. There are edge beams and columns, but no tie member between two
chosen points yet.</li>
<li><b>Inclined and point-free supports.</b> Supports are blocks on the surface; a hypar
resting on two low corners with a strut needs a support that takes thrust along a chosen
direction.</li>
</ul>
</div>
</section>
'''

BODY_4 = r'''
<section>
<span class="qnum">Unasked for</span>
<h2>Where I would do it differently</h2>
<div class="prose">
<ol>
<li><b>Cut, don't fade — but keep the ghost as its own feature.</b> Fading hides the staircase
instead of removing it, and the solver would keep solving the staircase. Fitting the mesh
fixes the looks, the area, the perimeter, the beam and the supports at once. Then ghosting the
<em>uncut parent surface</em> behind your piece is a second, separate switch — and it is the
picture you actually sent me.</li>
<li><b>Do the domain and the edge conditions in the same change.</b> A smooth ellipse whose
beams and supports are still on the rectangle would be a more convincing wrong answer than the
staircase is. They are one job.</li>
<li><b>Put two numbers in each card row.</b> Worst anywhere, and worst away from the support
blocks. On your own module all three worst elements are the same corner; a card that only ever
says "the corner" is a card you will stop reading.</li>
<li><b>Build your 1 m strip as a tool.</b> <code>H = q'L²/8f</code> on a strip you draw on the
model, printed next to the same strip's finite element result. It turns the app into something
that checks your poster instead of replacing it.</li>
<li><b>Name the presets after the shapes, in your language.</b> <i>sector elíptico</i>,
<i>sector bajo paraboloide</i>, <i>paraboloide rectangular</i> — the vocabulary on your poster,
so the preset list reads like your own drawing index.</li>
<li><b>Say the word "ghost" on the canvas.</b> The tab already writes in red when the drawn
thickness is exaggerated. A ghosted parent surface should get the same treatment: a line saying
what is structure and what is only reference.</li>
</ol>
</div>
</section>

<section>
<span class="qnum">Before I build</span>
<h2>Six questions</h2>
<div class="prose"><p>Each one has my default in case you would rather I just choose.
Answer only the ones where my default is wrong.</p></div>

<ol class="qs">
<li>
<h3>What does "elliptical sector" mean to you?</h3>
<p>Your picture shows a whole elliptical disc cut out of a saddle. Your poster uses the word
<i>sector</i> for a triangular piece between the asymptotes. Both are easy; they are different.</p>
<ul class="opts">
<li><b>(i)</b> the full elliptical disc, as in the picture you sent</li>
<li><b>(ii)</b> an angular wedge — between two rays from the centre</li>
<li><b>(iii)</b> the region between the asymptotes and a hyperbola, as on your poster</li>
</ul>
<p class="default"><b>Default:</b> the contour language does all three; I ship
<b>(i)</b> as the named preset and put (ii) and (iii) in the preset list beside it.</p>
</li>

<li>
<h3>What is "the sliced element"?</h3>
<ul class="opts">
<li><b>(a)</b> the governing element — the same one, said differently</li>
<li><b>(b)</b> the element the current section cut passes through</li>
<li><b>(c)</b> the 1 m design strip from your poster</li>
</ul>
<p class="default"><b>Default:</b> the card gets tension / compression / governing, the section
panel reports (b) as you move the cut, and I build (c) as the strip tool. If you meant only
(a), say so and I will drop a row.</p>
</li>

<li>
<h3>When the domain is cut, where do the edge beam and the supports go?</h3>
<p>Today they stay on the rectangle. On the ellipse above that means the shell hangs off four
tangent points of a beam ring it barely touches.</p>
<p class="default"><b>Default:</b> the edge beam follows the cut boundary, and support picking
works on the cut boundary's corners. I would also keep "beam on the rectangle" available,
because a shell cut with a hole in the middle still wants beams on its outer rectangle.</p>
</li>

<li>
<h3>Should the trimmed shape be the analysed shape, or only the drawn shape?</h3>
<p>Trimming only the drawing is a few hours. Fitting the mesh is a few days and changes the
numbers — slightly better ones, and honest ones.</p>
<p class="default"><b>Default:</b> analysed too. I would rather not draw a shape the solver
did not solve. If you want the quick version first to look at, I can ship the drawn trim with
a red line on the canvas saying the analysis is still on the staircase — but only as a
stepping stone.</p>
</li>

<li>
<h3>The contour: <code>g(x, y)</code> or <code>y</code> between two curves?</h3>
<ul class="opts">
<li><b>(i)</b> one signed expression <code>g(x, y)</code>, kept where it is negative —
does rings, discs, holes, anything closed</li>
<li><b>(ii)</b> a band, <code>y1(x) ≤ y ≤ y2(x)</code> — reads more like the way you wrote it,
easier for "between two parabolas", cannot do a ring</li>
</ul>
<p class="default"><b>Default:</b> (i) as the engine, with (ii) offered as a two-box shortcut
that writes an (i) expression for you, so you can type either and get the same boundary.</p>
</li>

<li>
<h3>How far do you want to go towards the 55 × 18 m assembly?</h3>
<p>One tile at a time covers everything on this page. Several tiles joined into one roof is a
real change to the model — several surfaces, shared edges, a ridge that is a beam.</p>
<p class="default"><b>Default:</b> not now. I finish the domain, the trimming, the edge
conditions and the card first, because the assembly needs all four of those to exist before it
is worth anything. Tell me if the assembly is the thing you actually need and I will re-order.</p>
</li>
</ol>
</section>

<section>
<h2>What I would build, in order</h2>
<div class="scroll"><table class="tbl">
<thead><tr><th style="width:7%">Step</th><th style="width:34%">What</th><th>Why it is in this position</th></tr></thead>
<tbody>
<tr><td class="num">1</td><td>The signed contour <code>g(x, y)</code> and its presets</td>
    <td>Everything else needs a boundary that is a curve.</td></tr>
<tr><td class="num">2</td><td>Fitted mesh at the boundary, with the sliver guard</td>
    <td>Makes the drawn shape and the solved shape the same shape.</td></tr>
<tr><td class="num">3</td><td>Edge beam and supports on the cut boundary</td>
    <td>The step that changes results, not looks. Cannot happen before 2.</td></tr>
<tr><td class="num">4</td><td>The governing card in the left rail</td>
    <td>No dependencies. Could be done first if you want something to hold this week.</td></tr>
<tr><td class="num">5</td><td>Ghost the parent surface</td>
    <td>Cheap, and best once the trimmed piece looks right to sit in front of it.</td></tr>
<tr><td class="num">6</td><td>The 1 m design strip, with your <code>H = q'L²/8f</code> beside the FE result</td>
    <td>Independent; goes with the card.</td></tr>
</tbody></table></div>
<p class="prose" style="color:var(--muted);font-size:.92rem;margin-top:26px">
Nothing above is built. The pictures of the grid, the three treatments and the fitted mesh are
drawn by the same centre test and the same node projection the code would use, so they cannot
flatter a method that would not work. The two photographs are the real tab, analysed this
morning on the <code>claude/shell-rc-rebuild</code> branch.</p>
</section>
</div>
'''


# ── the hand-composed figures ────────────────────────────────────────────
def support_tri(x, y, cls='sv-ink'):
    return (f'<polygon points="{x-6:.0f},{y+9:.0f} {x+6:.0f},{y+9:.0f} {x:.0f},{y:.0f}" '
            f'class="{cls}"/><line x1="{x-8:.0f}" y1="{y+9:.0f}" x2="{x+8:.0f}" '
            f'y2="{y+9:.0f}" class="sv-line"/>')


def fig_today_edge():
    grid, _, _ = figs.ellipse_cut(12, .86, .72, 200, show_centres=False, show_band=False)
    s = [f'<g transform="translate(24,24)">{grid}</g>']
    s.append('<rect x="24" y="24" width="200" height="200" class="sv-beam"/>')
    for x, y in ((24, 24), (224, 24), (24, 224), (224, 224)):
        s.append(support_tri(x, y))
    # the four tangent points where the shell actually reaches the ring
    for x, y in ((24, 124), (224, 124), (124, 52), (124, 196)):
        s.append(f'<circle cx="{x}" cy="{y}" r="4.5" class="sv-ink" opacity=".85"/>')
    s.append('<text x="124" y="248" text-anchor="middle" class="sv-t b">beam and supports on the rectangle</text>')
    s.append('<text x="124" y="262" text-anchor="middle" class="sv-t">shell reaches it at 4 points (dots)</text>')
    return '\n'.join(s)


def fig_want_edge():
    s = [f'<g transform="translate(24,24)">{figs.fitted_cut(12, .86, .72, 200)}</g>']
    s.append(f'<g transform="translate(24,24)"><path d="{figs._ell_d(.86, .72, 200)}" '
             f'class="sv-beam"/></g>')
    import math as _m
    for th in (45, 135, 225, 315):
        r = _m.radians(th)
        x = 24 + figs._px(.86 * _m.cos(r), 200)
        y = 24 + figs._px(.72 * _m.sin(r), 200)
        s.append(support_tri(x, y))
    s.append('<text x="124" y="248" text-anchor="middle" class="sv-t b">beam and supports on the cut</text>')
    s.append('<text x="124" y="262" text-anchor="middle" class="sv-t">true length 37.7 m, not 48.0 m</text>')
    return '\n'.join(s)


def arrow(x, y):
    return (f'<line x1="{x}" y1="{y}" x2="{x+30}" y2="{y}" class="sv-line" '
            f'stroke-width="1.4"/><polygon points="{x+30},{y-4} {x+38},{y} {x+30},{y+4}" '
            f'class="sv-mut"/>')


def fig_steps():
    s = []
    # 1 -- the surface
    s.append(f'<g transform="translate(6,30)">{figs.hypar_iso(None, 12, 260, 170, zfun=SADDLE)}</g>')
    s.append('<text x="136" y="22" text-anchor="middle" class="sv-t b">1 · the surface</text>')
    s.append('<text x="136" y="228" text-anchor="middle" class="sv-t">z = f(x, y) over the rectangle</text>')
    s.append(arrow(276, 118))
    # 2 -- the contour in plan
    s.append('<g transform="translate(336,42)">'
             f'<rect x="0" y="0" width="150" height="150" class="sv-line" stroke-dasharray="3 3"/>'
             f'<path d="{figs._ell_d(.86, .72, 150)}" class="cell-in"/>'
             f'<path d="{figs._ell_d(.86, .72, 150)}" class="curve"/>'
             '<text x="75" y="78" text-anchor="middle" class="sv-t b" '
             'style="font-size:12px">g &lt; 0</text>'
             '<text x="140" y="14" text-anchor="end" class="sv-t">g &gt; 0</text>'
             '</g>')
    s.append('<text x="411" y="22" text-anchor="middle" class="sv-t b">2 · the contour</text>')
    s.append('<text x="411" y="228" text-anchor="middle" class="sv-t">g(x, y) = 0 in plan</text>')
    s.append(arrow(556, 118))
    # 3 -- the trimmed shell
    s.append(f'<g transform="translate(616,30)">{F_ISO_TRIM}</g>')
    s.append('<text x="746" y="22" text-anchor="middle" class="sv-t b">3 · the shell</text>')
    s.append('<text x="746" y="228" text-anchor="middle" class="sv-t">trimmed, with an edge to build on</text>')
    return '\n'.join(s)


CARD_ROWS = [
    ('most tension', 'el 551', 'x 8.81  y 8.44', 'N₁ = +146.0 kN/m', 'red',
     '1.2D + 1.6Lr'),
    ('most compression', 'el 529', 'x 0.56  y 8.44', 'N₂ = −131.0 kN/m', 'blue',
     '1.2D + 1.6Lr'),
    ('governs the design', 'el 550', 'x 8.44  y 8.44', 'utilisation 2.40', 'amber',
     'shear into the support block'),
]


def fig_card():
    s = ['<rect x="1" y="1" width="398" height="354" rx="6" fill="var(--surface)" '
         'stroke="var(--line-hard)"/>']
    s.append('<text x="18" y="28" class="sv-t b" style="font-size:12.5px;letter-spacing:.06em">'
             'WHAT DECIDES THIS DESIGN</text>')
    s.append('<line x1="18" y1="38" x2="382" y2="38" class="sv-line"/>')
    y = 58
    for label, el, pos, val, colour, note in CARD_ROWS:
        s.append(f'<rect x="18" y="{y}" width="364" height="82" rx="4" '
                 f'fill="var(--{colour}-soft)" stroke="var(--{colour})" stroke-width="1"/>')
        s.append(f'<rect x="18" y="{y}" width="4" height="82" fill="var(--{colour})"/>')
        s.append(f'<text x="34" y="{y+20}" class="sv-t" style="font-size:10.5px;'
                 f'letter-spacing:.09em;fill:var(--{colour});font-weight:700">{label.upper()}</text>')
        s.append(f'<text x="34" y="{y+42}" class="sv-t b" style="font-size:15px;'
                 f'font-family:\'JetBrains Mono\',monospace">{val}</text>')
        s.append(f'<text x="34" y="{y+60}" class="sv-t" style="font-size:11px">{el} · {pos}</text>')
        s.append(f'<text x="34" y="{y+74}" class="sv-t" style="font-size:10.5px;opacity:.85">'
                 f'{note}</text>')
        s.append(f'<text x="366" y="{y+46}" text-anchor="end" class="sv-t" '
                 f'style="font-size:15px;fill:var(--{colour})">›</text>')
        y += 92
    s.append('<text x="18" y="348" class="sv-t" style="font-size:10px">click a row: turn to it, '
             'select it, cut a section through it</text>')
    return '\n'.join(s)


PAGE = (HEAD + BODY_1 + BODY_2 + BODY_3 + BODY_4
        ).replace('__FIG_CUT__', F_CUT) \
         .replace('__FIG_GHOST__', F_GHOST) \
         .replace('__FIG_TRIM__', F_TRIM) \
         .replace('__FIG_FIT__', F_FIT) \
         .replace('__FIG_TODAY_EDGE__', fig_today_edge()) \
         .replace('__FIG_WANT_EDGE__', fig_want_edge()) \
         .replace('__FIG_STEPS__', fig_steps()) \
         .replace('__FIG_CARD__', fig_card())

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else '../../SHELL_DOMAIN_NOTE_2026-09-21.html'
    for token in ('__FIG_',):
        assert token not in PAGE, 'a figure placeholder was left unfilled'
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(PAGE)
    print('wrote %s  (%.1f kB)' % (out, len(PAGE) / 1024))
