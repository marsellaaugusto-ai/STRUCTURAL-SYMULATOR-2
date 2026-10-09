"""Piece marks: which of these are the same thing, and how many of each.

A fabricator does not build a model, they build a list of pieces, and the
list says "T1, make twelve". Everything here exists to produce that list
from the model, and two decisions shape all of it.

THE FIRST: A MARK IS DERIVED, NEVER STORED. It is recomputed from the
geometry every time, the way a tonnage is. A mark someone could edit by
hand is a mark that can disagree with the steel, and a stored mark survives
the edit that made it wrong -- which is the one failure that reaches the
shop floor. (Keeping a number stable ACROSS REVISIONS is a different and
harder problem, and deliberately not solved here: these marks are correct
for the model in front of you, not comparable with last week's drawing.)

THE SECOND: ERR TOWARD "DIFFERENT". Marking two identical trusses apart
costs a duplicated drawing and a shrug. Marking two different trusses the
same sends the wrong steel to site. So every judgement call below -- the
rounding, the tie handling, the bail-out on structures too symmetric to
canonicalise -- resolves toward splitting a mark rather than merging one.
Nothing here ever claims two things are the same without having compared
their full geometry.

TWO LEVELS, because a shop uses both:

  * A PART is one rod: one piece of steel, cut to a length, with a section
    and an end treatment. Two rods are one part when those agree. This is
    the bar list someone orders from, and it is exact.

  * An ASSEMBLY is a group: several rods fabricated and shipped as one
    piece. Two groups are one assembly when their rods have the same shape,
    wherever they sit and however they are turned -- which is a harder
    question than it looks, and `assembly_signature` is the answer.

TOLERANCE IS A SETTING, because exact float comparison is useless here. Two
trusses drawn by the same parametric generator agree to the last bit; two
drawn by hand, or imported through a DXF, agree to about a millimetre.
Lengths are rounded to `tol_mm` before anything is compared, so the
comparison asks "the same to the nearest millimetre?" rather than "the same
double?". Rounding has a boundary: two lengths half a tolerance apart can
land either side of it and be marked apart. That is the safe direction, and
it is why the tolerance is yours to set rather than ours to guess.
"""
import hashlib
import math
import struct

from apps.stereo import stereo_groups as sgp

# A millimetre. Fine enough that nothing a person would call the same part
# is split, coarse enough to absorb what a drawing exchange does to a
# coordinate.
DEFAULT_TOL_MM = 1.0
# Below this a tolerance stops meaning anything -- rounding to a tenth of a
# micron is exact float comparison with extra steps.
MIN_TOL_MM = 0.001
MAX_TOL_MM = 100.0

PART_PREFIX = 'B'          # Bar.
ASSEMBLY_PREFIX = 'T'      # The marks a truss shop writes.
MIRROR_SUFFIX = '/m'

# A structure symmetric enough to need more candidate frames than this is
# one we decline to canonicalise, and its group gets a mark of its own. See
# `assembly_signature`.
MAX_FRAMES = 4096

STEEL_KG_PER_M3 = 7850.0
STEEL_KN_PER_M3 = 78.5


def clamp_tol(tol_mm):
    """A usable tolerance from whatever was typed, saved or left out."""
    try:
        tol = float(tol_mm)
    except (TypeError, ValueError):
        return DEFAULT_TOL_MM
    if not math.isfinite(tol) or tol <= 0.0:
        return DEFAULT_TOL_MM
    return min(MAX_TOL_MM, max(MIN_TOL_MM, tol))


# ── one rod ───────────────────────────────────────────────────────────────

def rod_length(nodes, member):
    ax, ay, az = nodes[member['a']]
    bx, by, bz = nodes[member['b']]
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2)


def rod_mass_kg(nodes, member, length=None):
    L = rod_length(nodes, member) if length is None else length
    A_m2 = (member.get('A', 0.0) or 0.0) * 1e-4
    rho = (float(member['gamma_kN_m3']) * 1000.0 / 9.80665
           if member.get('gamma_kN_m3') else STEEL_KG_PER_M3)
    return A_m2 * L * rho


def _q(value, tol):
    """A length quantised to the tolerance, as an int, for hashing."""
    return int(round(float(value) / tol))


def section_key(member):
    """What makes two rods different pieces of steel, apart from length.

    A named profile is the whole answer when both rods carry one -- that is
    what a shop orders by. Without a name, the section properties stand in
    for it, because two rods with the same A and I are the same bar whatever
    the model forgot to call it. The connection comes in because a welded
    end and a bolted end are different shop work on the same bar, and
    material strength because two visually identical bars in S235 and S355
    are not interchangeable.
    """
    profile = str(member.get('profile') or '').strip()
    if profile:
        shape = ('p', profile)
    else:
        shape = ('s',) + tuple(
            round(float(member.get(k, 0.0) or 0.0), 6)
            for k in ('A', 'I', 'J', 'Iw', 'c_cm', 'cw_cm', 'r_gyr'))
    return shape + (
        str(member.get('conn') or 'pin'),
        round(float(member.get('Fy', 0.0) or 0.0), 3),
        round(float(member.get('Fu', 0.0) or 0.0), 3),
        round(float(member.get('E', 0.0) or 0.0), 3),
        bool(member.get('cable')),
        round(float(member.get('gamma_kN_m3', 0.0) or 0.0), 4),
    )


def part_key(nodes, member, tol_mm=DEFAULT_TOL_MM):
    """The identity of one rod as a piece of steel: section plus length."""
    tol = clamp_tol(tol_mm) / 1000.0
    return section_key(member) + (_q(rod_length(nodes, member), tol),)


# ── a group, wherever it sits and however it is turned ────────────────────

def _centroid(pts):
    n = float(len(pts))
    return (sum(p[0] for p in pts) / n,
            sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return None if n < 1e-12 else (a[0] / n, a[1] / n, a[2] / n)


def _frames(pts, tol):
    """Candidate orthonormal frames chosen by the point cloud itself.

    The first axis points at whichever node sits farthest from the centroid,
    the second at the farthest node that is not on that line. Both are
    intrinsic properties of the cloud, so a rotated copy of it yields the
    rotated copy of each frame -- which is exactly what makes the canonical
    form invariant. Where several nodes tie for farthest, every one of them
    is a candidate and the smallest resulting hash wins; a tie IS the
    symmetry, so enumerating it is the only honest way to break it.
    """
    far = [(_norm(p), i) for i, p in enumerate(pts)]
    best = max(d for d, _ in far)
    if best < tol:                      # every node on top of the centroid
        return []
    firsts = [i for d, i in far if abs(d - best) < tol]

    out = []
    for i in firsts:
        e1 = _unit(pts[i])
        if e1 is None:
            continue
        # The farthest node off the e1 line, by perpendicular distance.
        perp = []
        for j, p in enumerate(pts):
            along = _dot(p, e1)
            r = _sub(p, (e1[0] * along, e1[1] * along, e1[2] * along))
            perp.append((_norm(r), j, r))
        wide = max(d for d, _, _ in perp)
        if wide < tol:
            # Collinear: the cloud is rotationally symmetric about e1, so
            # any perpendicular pair gives the same canonical coordinates
            # (every point lands at (t, 0, 0)). One fixed choice is enough.
            ref = (0.0, 0.0, 1.0) if abs(e1[2]) < 0.9 else (1.0, 0.0, 0.0)
            e2 = _unit(_cross(e1, ref))
            out.append((e1, e2, _cross(e1, e2)))
            continue
        for d, _j, r in perp:
            if abs(d - wide) >= tol:
                continue
            e2 = _unit(r)
            if e2 is None:
                continue
            out.append((e1, e2, _cross(e1, e2)))
            if len(out) > MAX_FRAMES:
                return None
    return out or []


def _canonical(pts, rods, tol, handed):
    """(spelling, rod_order) for this cloud, or None.

    The smallest spelling over every candidate frame, and the order its
    bars came out in. The spelling is the identity -- what gets hashed --
    and the order is the CORRESPONDENCE: two copies of one part spell the
    same, so their bars come out in the same order, and zipping the two
    orders says which bar of one is which bar of the other. That is what
    lets a section applied to one copy land on the matching bar of all of
    them (see stereo_components).

    `handed` is +1 for the cloud as drawn and -1 for its mirror image: the
    third axis is flipped, which reflects the whole cloud. A part and its
    mirror are different shop pieces -- one cannot be installed where the
    other goes -- so they are compared separately and marked apart.

    None means the cloud gave us nothing to work from: every node on the
    centroid, or so symmetric that enumerating the candidate frames ran
    past MAX_FRAMES.
    """
    c = _centroid(pts)
    local = [_sub(p, c) for p in pts]
    frames = _frames(local, tol)
    if frames is None:
        return None
    if not frames:
        # Every node on the centroid: a collapsed group, with no shape to
        # compare. Refuse rather than hash the node count, or two unrelated
        # collapsed groups would come out as the same part.
        return None

    best = None
    for e1, e2, e3 in frames:
        if handed < 0:
            e3 = (-e3[0], -e3[1], -e3[2])
        placed = [(_q(_dot(p, e1), tol), _q(_dot(p, e2), tol),
                   _q(_dot(p, e3), tol)) for p in local]
        order = sorted(range(len(placed)), key=lambda i: placed[i])
        where = {old: new for new, old in enumerate(order)}
        bars = sorted(
            ((min(where[a], where[b]), max(where[a], where[b]), key), k)
            for k, (a, b, key) in enumerate(rods))
        spelling = (tuple(placed[i] for i in order),
                    tuple(bar for bar, _k in bars))
        if best is None or spelling < best[0]:
            best = (spelling, tuple(k for _bar, k in bars))
    return best


def assembly_signature(nodes, members, rods, tol_mm=DEFAULT_TOL_MM):
    """(as_drawn, mirrored) hashes for a set of rods, or (None, None).

    Two sets of rods with the same `as_drawn` hash are the same fabricated
    part: the same bars, in the same arrangement, to within the tolerance --
    wherever in the model they sit and whichever way they are turned. One
    whose `as_drawn` equals another's `mirrored` is that part's mirror
    image, which is a different piece of steel and gets its own mark.

    (None, None) means "do not claim anything about this one": too few rods
    to have a shape, every node collapsed onto one point, or a cloud so
    symmetric that enumerating its candidate frames ran past MAX_FRAMES.
    Refusing is the safe answer, and the caller gives such a group a mark
    of its own.
    """
    rods = [i for i in rods if 0 <= i < len(members)]
    if not rods:
        return (None, None)
    tol = clamp_tol(tol_mm) / 1000.0
    idx = sgp.nodes_of_rods(members, sorted(rods))
    if len(idx) < 2:
        return (None, None)
    at = {n: k for k, n in enumerate(idx)}
    pts = [nodes[n] for n in idx]
    bars = [(at[members[i]['a']], at[members[i]['b']], section_key(members[i]))
            for i in sorted(rods)]

    out = []
    for handed in (1, -1):
        found = _canonical(pts, bars, tol, handed)
        if found is None:
            return (None, None)
        h = hashlib.sha256()
        h.update(b'STEREO-MARK/1|%d|' % _q(tol, 1e-9))
        h.update(repr(found[0]).encode())
        out.append(h.hexdigest())
    return (out[0], out[1])


def canonical_order(nodes, members, rods, tol_mm=DEFAULT_TOL_MM, handed=1):
    """This group's rods in canonical order, or None.

    The correspondence between copies of one part: two groups whose
    signatures match spell the same, so their canonical orders line up
    position for position and `zip` of the two says which rod of one is
    which rod of the other. For a MIRRORED copy pass handed=-1, which is
    the spelling its mirror signature came from.

    None whenever `assembly_signature` would refuse -- there is no
    correspondence to offer for a group we declined to compare.
    """
    rods = sorted(i for i in rods if 0 <= i < len(members))
    if not rods:
        return None
    tol = clamp_tol(tol_mm) / 1000.0
    idx = sgp.nodes_of_rods(members, rods)
    if len(idx) < 2:
        return None
    at = {n: k for k, n in enumerate(idx)}
    pts = [nodes[n] for n in idx]
    bars = [(at[members[i]['a']], at[members[i]['b']], section_key(members[i]))
            for i in rods]
    found = _canonical(pts, bars, tol, handed)
    if found is None:
        return None
    return [rods[k] for k in found[1]]


# ── assigning the marks ───────────────────────────────────────────────────

def mark_number(mark):
    """The integer in 'T12/m'. Sorting marks as text puts T10 before T2."""
    body = str(mark or '')
    if body.endswith(MIRROR_SUFFIX):
        body = body[:-len(MIRROR_SUFFIX)]
    digits = ''.join(c for c in body if c.isdigit())
    return int(digits) if digits else 0


def _numbered(buckets, prefix, order):
    """{key: mark} for buckets sorted by `order`, numbered from 1.

    The most-used part is T1. A fabricator reads the list top down and the
    repeated work should be at the top; it also means a model's headline
    part keeps its number when something rare is added or removed.
    """
    marks = {}
    for n, key in enumerate(sorted(buckets, key=order), start=1):
        marks[key] = '%s%d' % (prefix, n)
    return marks


def part_marks(nodes, members, tol_mm=DEFAULT_TOL_MM):
    """Marks for single rods: (by_rod, rows).

    `by_rod` is a list as long as `members`, each entry that rod's mark.
    `rows` is one entry per mark, for the schedule.
    """
    tol = clamp_tol(tol_mm)
    buckets = {}
    for i, m in enumerate(members):
        a, b = m.get('a'), m.get('b')
        if not (isinstance(a, int) and isinstance(b, int)
                and 0 <= a < len(nodes) and 0 <= b < len(nodes)):
            continue
        buckets.setdefault(part_key(nodes, m, tol), []).append(i)

    def order(key):
        rods = buckets[key]
        return (-len(rods), -rod_length(nodes, members[rods[0]]), repr(key))

    marks = _numbered(buckets, PART_PREFIX, order)
    by_rod = [None] * len(members)
    rows = []
    for key, rods in buckets.items():
        for i in rods:
            by_rod[i] = marks[key]
        m = members[rods[0]]
        L = rod_length(nodes, m)
        rows.append({
            'mark': marks[key],
            'profile': str(m.get('profile') or '') or '(unnamed section)',
            'conn': str(m.get('conn') or 'pin'),
            'length_m': L,
            'qty': len(rods),
            'total_length_m': L * len(rods),
            'mass_kg': rod_mass_kg(nodes, m, L),
            'total_mass_kg': rod_mass_kg(nodes, m, L) * len(rods),
            'roles': sorted({str(members[i].get('role') or '')
                             for i in rods} - {''}),
            'rods': sorted(rods),
        })
    rows.sort(key=lambda r: mark_number(r['mark']))
    return by_rod, rows


def assembly_marks(nodes, members, groups, tol_mm=DEFAULT_TOL_MM):
    """Marks for groups: (by_gid, rows).

    A group is compared on its OWN rods, not its subtree: a parent and its
    child would otherwise be compared against each other on overlapping
    steel, and the parent of one truss would look like the truss. A group
    with no rods of its own is a branch of the tree, not a piece, and gets
    no mark.

    Mirrored copies share the base number and are told apart by a `/m`
    suffix, so the schedule reads "T3 x4, T3/m x4" -- eight trusses, two
    drawings, and nobody bolting a left-hand one into a right-hand bay.
    """
    tol = clamp_tol(tol_mm)
    sigs, own = {}, {}
    for g in groups:
        rods = sorted(g['members'])
        if not rods:
            continue
        own[g['id']] = rods
        sigs[g['id']] = assembly_signature(nodes, members, rods, tol)

    # Buckets keyed by the part, with its mirror folded in: the first
    # spelling seen names the bucket, and a later group matching it the
    # other way round joins as a mirror. A group we declined to compare
    # (signature None) is its own bucket, which is the safe answer.
    buckets, home = {}, {}
    for gid in sorted(own):
        drawn, mirror = sigs[gid]
        if drawn is None:
            buckets[('alone', gid)] = [(gid, False)]
            home[gid] = ('alone', gid)
            continue
        if ('part', drawn) in buckets:
            key, flipped = ('part', drawn), False
        elif ('part', mirror) in buckets:
            key, flipped = ('part', mirror), True
        else:
            key, flipped = ('part', drawn), False
        buckets.setdefault(key, []).append((gid, flipped))
        home[gid] = key

    def length_of(gid):
        return sum(rod_length(nodes, members[i]) for i in own[gid])

    def order(key):
        members_in = buckets[key]
        gid = members_in[0][0]
        return (-len(members_in), -length_of(gid), -len(own[gid]), gid)

    base = _numbered(buckets, ASSEMBLY_PREFIX, order)
    by_gid, rows = {}, []
    for key, found in buckets.items():
        for gid, flipped in found:
            by_gid[gid] = base[key] + (MIRROR_SUFFIX if flipped else '')
        for flipped in (False, True):
            same = [gid for gid, f in found if f is flipped]
            if not same:
                continue
            gid = same[0]
            rods = own[gid]
            L = length_of(gid)
            mass = sum(rod_mass_kg(nodes, members[i]) for i in rods)
            rows.append({
                'mark': base[key] + (MIRROR_SUFFIX if flipped else ''),
                'names': sorted({g['name'] for g in groups
                                 if g['id'] in same}),
                'qty': len(same),
                'n_rods': len(rods),
                'length_m': L,
                'total_length_m': L * len(same),
                'mass_kg': mass,
                'total_mass_kg': mass * len(same),
                'mirrored': flipped,
                'gids': sorted(same),
            })
    rows.sort(key=lambda r: (mark_number(r['mark']), r['mirrored']))
    return by_gid, rows


def schedule(nodes, members, groups=(), tol_mm=DEFAULT_TOL_MM):
    """Everything the piece-mark sheet needs, in one call."""
    by_rod, parts = part_marks(nodes, members, tol_mm)
    by_gid, assemblies = assembly_marks(nodes, members, groups or (), tol_mm)
    return {'tol_mm': clamp_tol(tol_mm),
            'part_of_rod': by_rod, 'parts': parts,
            'mark_of_group': by_gid, 'assemblies': assemblies}
