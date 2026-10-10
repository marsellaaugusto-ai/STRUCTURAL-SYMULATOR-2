"""A part saved to a file, to be placed in another model.

A component says two groups in ONE model are the same fabricated part
(stereo_components). This is the same idea across files: a truss worked
out once, saved, and placed in the next project -- with its sections,
because reusing a truss that arrives without its steel is reusing a
sketch.

WHAT A PART FILE IS. Its own little model: nodes, members with everything
they carry, and the named profiles those members refer to. Nothing about
where it came from, because that is the one thing that does not transfer.

    A NODE GOES WHERE YOU PUT IT, and it has to be a node rather than a
    corner of the bounding box. The two are usually not the same point --
    a truss's lowest x, lowest y and lowest z rarely meet at one joint --
    and anchoring on a box corner means placing a part on a node of the
    structure lands NOTHING on that node, so nothing fuses and the part
    floats beside the model instead of being bolted to it.

    So the anchor is the part's own node nearest that corner, ties broken
    by the lower number: predictable, visible, and something that can
    actually meet another node. A centroid would be invisible and usually
    not a node either.

PLACING IS A MERGE, not a second paste path. stereo_merge.merge_models
already welds coincident nodes, renames a group whose name is taken,
reports a profile that means something different here, and keeps a rod in
one group only. A part dropped onto an existing model has every one of
those problems, and solving them again here would be solving them
differently.

    WHICH MEANS RODS FUSE. Two rod ends at the same point become one node,
    because in this app a container bounds ownership and never connection
    -- a part placed touching the structure is bolted to it, not floating
    beside it. That is the opposite of a drawing tool, and it is right
    here: a joint nobody drew is a hinge nobody drew.

EVERY COPY PLACED IS ONE COMPONENT. A part carries its name, and each
placement becomes a group declared a copy of it, so three placements are
three copies of one drawing -- sized together, marked once. That is what
makes a library worth having rather than a way of duplicating geometry.
"""
import datetime
import json
import os

from apps.stereo import stereo_groups as sgp
from apps.stereo import stereo_marks as sm

#: The format string every part file carries. A reader that does not know
#: it refuses rather than guessing at the fields.
FORMAT = 'STEREO-PART/1'

#: What a part file is called when nothing else is asked for.
SUFFIX = '.part.json'


class PartError(ValueError):
    """A file that is not a part this version can read."""


# ── making one ────────────────────────────────────────────────────────────

def make_part(nodes, members, rods, name, profiles=None,
              tol_mm=sm.DEFAULT_TOL_MM):
    """A part record from a set of rods of a model.

    The rods keep everything they carry except their endpoints, which
    become the part's own node numbering. Only the profiles those rods
    actually name come along -- a library part should not drag a whole
    project's section list behind it.
    """
    rods = sorted(i for i in rods if 0 <= i < len(members))
    if not rods:
        raise PartError('A part needs at least one rod.')
    idx = sgp.nodes_of_rods(members, rods)
    if len(idx) < 2:
        raise PartError('A part needs at least two nodes.')

    pts = [nodes[n] for n in idx]
    low = (min(p[0] for p in pts), min(p[1] for p in pts),
           min(p[2] for p in pts))
    # The node nearest that corner, which is what a placement actually
    # lands on. Ties go to the lower number so the same part always
    # anchors on the same joint.
    anchor = min(range(len(pts)),
                 key=lambda k: (sum((pts[k][d] - low[d]) ** 2
                                    for d in range(3)), k))
    origin = pts[anchor]
    at = {n: k for k, n in enumerate(idx)}
    want = set()
    out = []
    for i in rods:
        m = members[i]
        rest = {k: v for k, v in m.items() if k not in ('a', 'b')}
        if rest.get('profile'):
            want.add(str(rest['profile']))
        out.append(dict(rest, a=at[m['a']], b=at[m['b']]))

    local = [(p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
             for p in pts]
    drawn, _mirror = sm.assembly_signature(nodes, members, rods, tol_mm)
    return {
        'format': FORMAT,
        'name': (str(name).strip() or 'Part'),
        'saved': datetime.datetime.now().replace(microsecond=0).isoformat(),
        'tol_mm': sm.clamp_tol(tol_mm),
        'signature': drawn,
        'anchor': anchor,
        'nodes': [list(p) for p in local],
        'members': out,
        'profiles': {k: dict(v) for k, v in (profiles or {}).items()
                     if k in want},
        'n_rods': len(out),
        'length_m': sum(sm.rod_length(nodes, members[i]) for i in rods),
        'mass_kg': sum(sm.rod_mass_kg(nodes, members[i]) for i in rods),
    }


# ── the file ──────────────────────────────────────────────────────────────

def save_part(part, path):
    """Write a part, atomically. Returns the path written.

    Atomic for the reason every save here is: a library someone is adding
    to over months must not be left with a half-written file where a part
    used to be.
    """
    import tempfile
    folder = os.path.dirname(os.path.abspath(path)) or '.'
    text = json.dumps(part, indent=1, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_part(path):
    """Read a part file, or raise PartError saying what is wrong with it.

    Checked rather than trusted: a file edited by hand, or written by a
    later version, must be refused with a reason instead of placing
    geometry that references nodes it does not have.
    """
    try:
        with open(path, encoding='utf-8') as fh:
            part = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PartError('%s could not be read: %s'
                        % (os.path.basename(path), exc))
    if not isinstance(part, dict):
        raise PartError('%s is not a part file.' % os.path.basename(path))
    if part.get('format') != FORMAT:
        raise PartError('%s says it is "%s"; this version reads "%s".'
                        % (os.path.basename(path), part.get('format'),
                           FORMAT))
    nodes = part.get('nodes')
    members = part.get('members')
    if not isinstance(nodes, list) or not isinstance(members, list):
        raise PartError('%s has no geometry in it.' % os.path.basename(path))
    if len(nodes) < 2 or not members:
        raise PartError('%s holds nothing to place.'
                        % os.path.basename(path))
    for p in nodes:
        if not (isinstance(p, (list, tuple)) and len(p) == 3):
            raise PartError('%s has a node that is not a point.'
                            % os.path.basename(path))
    for m in members:
        a, b = m.get('a'), m.get('b')
        if not (isinstance(a, int) and isinstance(b, int)):
            raise PartError('%s has a rod with no ends.'
                            % os.path.basename(path))
        if not (0 <= a < len(nodes) and 0 <= b < len(nodes)):
            raise PartError('%s has a rod pointing at a node it does not '
                            'have.' % os.path.basename(path))
    return part


def list_parts(folder):
    """Every part in a folder, as (path, part-or-None, error-or-None).

    One unreadable file does not hide the rest of a library.
    """
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        if not name.endswith(SUFFIX):
            continue
        path = os.path.join(folder, name)
        try:
            out.append((path, load_part(path), None))
        except PartError as exc:
            out.append((path, None, str(exc)))
    return out


def describe(part):
    """One line for a list of parts."""
    return '%s — %d rod(s), %.2f m, %.0f kg' % (
        part.get('name', '?'), part.get('n_rods', 0),
        part.get('length_m', 0.0), part.get('mass_kg', 0.0))


# ── placing it ────────────────────────────────────────────────────────────

def anchor_of(part):
    """Which of the part's nodes lands on the point it is placed at.

    Absent from a file written before there was one, where the geometry
    was stored against the bounding-box corner -- then nothing is at the
    origin and the placement is a plain offset, which is what that file
    meant.
    """
    k = part.get('anchor')
    return k if isinstance(k, int) and 0 <= k < len(part['nodes']) else None


def as_model(part, at=(0.0, 0.0, 0.0), name=None):
    """The part as something stereo_merge can merge in.

    One group holding every rod, declared a copy of the part -- so a
    second placement of the same file is the same component, sized
    together and marked once, without anyone saying so afterwards.
    """
    dx, dy, dz = at
    nodes = [(p[0] + dx, p[1] + dy, p[2] + dz) for p in part['nodes']]
    members = [dict(m) for m in part['members']]
    label = str(name or part.get('name') or 'Part')
    return {
        'nodes': nodes,
        'members': members,
        'loads': [],
        'supports': [],
        'groups': [{'id': 1, 'name': label, 'parent': None,
                    'members': set(range(len(members))),
                    'component': part.get('name') or label}],
        'profiles': {k: dict(v)
                     for k, v in (part.get('profiles') or {}).items()},
    }


def size(part):
    """(dx, dy, dz) the part occupies, for saying where it will land."""
    pts = part.get('nodes') or []
    if not pts:
        return (0.0, 0.0, 0.0)
    return tuple(max(p[k] for p in pts) - min(p[k] for p in pts)
                 for k in range(3))
