"""A goal and a few questions for each example in the library.

An example on its own shows what the program can build; a question makes
someone look at it. Each lesson names one idea the example is good for and
asks two or three things to try -- remove a support, play the load, explain
a rod -- whose answers are on the screen, not in this file. The questions
were written against what the examples actually do under their own loads,
and TestExampleLessons in tests/test_stereo_app.py holds them to it: the
bridge as shipped fails, the dome's pinned base takes its thrust so no hoop
is in tension, the cone's diagonals carry nothing under a symmetric load. A
question whose premise the model contradicts would teach the wrong thing.

Keyed by the example builder's name (stereo_examples.EXAMPLES), so a
renamed menu label cannot orphan its lesson. Kept free of Tk.
"""

LESSONS = {
    'planar_grid_with_columns_1': {
        'goal': 'Four columns hold a flat roof: see how the load gathers '
                'into them, and what the beam across the middle is for.',
        'questions': (
            'Colour by axial force. Which rods work hardest: the grid by '
            'the columns, the capital legs, or the beam? Why there?',
            'Results → Show me the governing rod, then Explain this rod. '
            'Does tension, compression or buckling govern it?',
            'Add-ons → Clear every beam, then ▶ Analyze. How much does the '
            'governing utilisation change? What was the beam doing?',
        ),
    },
    'planar_grid_with_columns_2': {
        'goal': 'One central column carries most of a 16 m roof, and four '
                'corner supports stop it rocking. As shipped it fails: '
                'find out where, and why.',
        'questions': (
            'Results → Show me the governing rod. Where is it, and what '
            'is it doing there?',
            'Colour by axial force. The ring at the top of the capital is '
            'in tension: why would the legs of a capital pull it apart?',
            'Support → tick the sandbox, click the four corner supports '
            'off and ▶ Analyze. What does the orange drawing show? Why '
            'can one point not hold a pin-jointed roof?',
        ),
    },
    'single_surface_truss_1': {
        'goal': 'A surface curved the same way in both directions carries '
                'load by arching both ways at once.',
        'questions': (
            'Colour by axial force. Are the top-layer rods mostly in '
            'compression or in tension? And the bottom layer?',
            'Display ▾ → Reactions. Do the supports only push up, or '
            'sideways too? What is that sideways push for?',
            '▶ Play load. Where does the shape move most?',
        ),
    },
    'single_surface_truss_2': {
        'goal': 'A half-cylinder curves one way only: across, it is an '
                'arch; along, it spans like a deep beam.',
        'questions': (
            'Colour by axial force. Compare rods running round the arch '
            'with rods running along the vault: which carry more?',
            'Support → sandbox: switch off the supports along one long '
            'edge and ▶ Analyze. Can an arch stand on one foot?',
            'The pattern is triangles. Why does a triangle need no '
            'diagonal to keep its shape, and a square does?',
        ),
    },
    'two_surface_truss_1': {
        'goal': 'A dish over a flat plane makes a grid that is deep in the '
                'middle and shallow at the edges: see what depth buys.',
        'questions': (
            'Where is the grid deepest, and where shallowest? Colour by '
            'utilization: which part works harder?',
            'Click a web rod at the centre and one near an edge, and '
            'Explain this rod for each. Which is longer, and what does '
            'that do to its K·L/r and its buckling strength?',
            '▶ Play load. Which rod comes nearest its capacity?',
        ),
    },
    'two_surface_truss_2': {
        'goal': 'Two domes, one inside the other, make a deep double-layer '
                'dome: see how ribs and rings share the load.',
        'questions': (
            'Colour by axial force. Which rods are in tension, and where '
            'are they?',
            'Display ▾ → Reactions. How much of the reaction at the base '
            'is horizontal? What would the dome do on rollers?',
            'Support → sandbox: switch off a few neighbouring base '
            'supports. Does the dome share the load out, or come apart?',
        ),
    },
    'barrel_vault_example': {
        'goal': 'A barrel vault bears along its two long springing lines, '
                'like a row of arches side by side.',
        'questions': (
            'Display ▾ → Reactions. The supports push outward as well as '
            'up: that is the thrust every arch needs held. How big is it '
            'next to the vertical load?',
            'Support → sandbox: free the supports along one springing '
            'line. What happens? What could hold the thrust instead?',
            'Colour by axial force. The vault is mostly in compression: '
            'which rods are in tension, and why those?',
        ),
    },
    'dome_example': {
        'goal': 'A ribbed dome: meridian ribs bring the load down, hoops '
                'hold them in shape.',
        'questions': (
            'Colour by axial force. Is any hoop in tension? A dome on a '
            'free base needs a tension ring at its foot: what is doing '
            'that job here? (Display ▾ → Reactions.)',
            'Which carry more, the meridians or the hoops? Where along '
            'a meridian is its force largest?',
            '▶ Play load and watch the crown. Where does the dome move '
            'most?',
        ),
    },
    'cone_roof_example': {
        'goal': 'The dome’s ribs and rings on straight lines: compare how '
                'a cone and a dome carry the same kind of load.',
        'questions': (
            'Colour by axial force. The diagonals carry nothing under '
            'this load. Why not? What load would make them work?',
            'Load the Schwedler dome too and compare the weights and '
            'the governing utilisations in Results. What does the '
            'curve buy?',
            'Click a rod at the apex and Explain this rod. Which limit '
            'governs it?',
        ),
    },
    'groin_vault_example': {
        'goal': 'Two barrel vaults crossing at diagonal groins, standing '
                'on all four walls.',
        'questions': (
            'Colour by axial force. Do the groin ridges carry more than '
            'the vault surfaces between them?',
            'Display ▾ → Reactions. Where along the walls are the '
            'reactions largest?',
            'Support → sandbox: switch off the supports along the middle '
            'of one wall. Does the vault still stand? Which rods take over?',
        ),
    },
    'truss_bridge_example': {
        'goal': 'A truss bridge on four pinned bearings. As shipped it '
                'fails: make it pass with as little added steel as you can.',
        'questions': (
            '▶ Play load. At what percentage of the load does the first '
            'rod reach its capacity, and which rod is it?',
            'Colour by axial force. The top chord is all compression, '
            'but the bottom chord is not all tension. Display ▾ → '
            'Reactions: the bearings push sideways. What would a roller '
            'at one end change?',
            'Change sections (Section mode) until it passes, and watch '
            'the weight at the top of Results. Who in the class has the '
            'lightest bridge that passes?',
        ),
    },
    'two_surface_isometric': {
        'goal': 'The same dish over a plane as the square example, '
                'triangulated instead: compare the two patterns.',
        'questions': (
            'Load the square version too (Two-surface truss: dish over '
            'flat plane) and compare the weight and the governing '
            'utilisation in Results. Which pattern does more with less?',
            'Look at the edges. Why are the boundary rows half-cells?',
            'Colour by utilization. Are the rods more evenly used here '
            'than in the square pattern?',
        ),
    },
    'bezier_extruded_vault': {
        'goal': 'A vault whose section is a curve you can reshape by hand: '
                'see how the shape steers the forces.',
        'questions': (
            'Tick Live, then go to Shape and drag the crown control point '
            'down. What happens to the forces as the arch gets flatter?',
            'Colour by axial force. Where does the flatter crown put rods '
            'into tension?',
            'Drag it back up past the original. Is a taller arch always '
            'better? Watch the weight and the governing rod in Results.',
        ),
    },
    'bezier_spun_tower': {
        'goal': 'A waisted tower made by spinning a curve, a shape no '
                'height field can describe.',
        'questions': (
            'Colour by axial force. Under its own weight, which rings are '
            'in tension: at the waist, or where it flares?',
            'Load → turn on the wind and ▶ Play load. Where does the '
            'tower move most?',
            'Shape → drag a control point to pinch the waist further. How '
            'do the waist rings respond?',
        ),
    },
    'bezier_patch_dish': {
        'goal': 'A dish whose surface is a grid of control heights: raise '
                'and lower them to see how shape steers load.',
        'questions': (
            'Tick Live. In Shape, raise one control point near an edge '
            'into a bump. Which rods work harder around it?',
            'The Shape panel says why a patch can follow this dish but '
            'not a surface with two waves. What is the reason?',
            'Flatten the whole patch. How do the weight and the governing '
            'utilisation compare with the curved dish?',
        ),
    },
    'rod_load_purlin_roof': {
        'goal': 'A load along the top rods, like purlins, bends each rod '
                'between its joints: the one case where shear and moment '
                'change along a rod.',
        'questions': (
            'Colour by Moment along rod, with Smooth gradient on. Where '
            'along each loaded rod is the moment largest?',
            'Click a loaded top rod and Explain this rod. How much of '
            'its utilisation comes from bending (H1-1)?',
            'Load → Clear rod loads and put the same total on as an area '
            'load at the nodes. How does the governing rod change?',
        ),
    },
    'billow_shell_chapel': {
        'goal': 'A shell curved both ways, rising at the corners and '
                'dipping between them, working almost all in compression.',
        'questions': (
            'Display ▾ → Reactions. Which supports take the most: the '
            'high corners or the low mid-edges?',
            'Colour by axial force. Which rods, if any, are in tension?',
            '▶ Play load. Where does the shell move most?',
        ),
    },
}


def lesson_for(builder):
    """The lesson of an example builder (or its name), or None."""
    name = builder if isinstance(builder, str) else getattr(
        builder, '__name__', '')
    return LESSONS.get(name)
