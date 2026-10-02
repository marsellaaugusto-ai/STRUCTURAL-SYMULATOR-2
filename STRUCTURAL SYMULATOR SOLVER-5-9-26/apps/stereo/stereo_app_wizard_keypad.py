"""The Custom Surface Wizard's maths keypad.

The wizard used to offer a flat row of ASCII buttons -- `sqrt`, `pi`, `^`,
`*`, `abs` -- which is the transliteration a parser needs, not the notation
anyone writes a surface in. These keys carry the real glyphs instead (√, π,
x², |x|, ×) and insert the ASCII behind the user's back, so what you type
reads like the mathematics and what expr_math compiles stays inside its
whitelist.

Three tabs, grouped by what the keys are for:

  Numbers      the variables and constants on top, then a numeric pad in
               the usual calculator order with the four operations beside
               it, and powers, roots and brackets down the right-hand side.
  Functions    trigonometric, hyperbolic, logarithmic and rounding
               functions of one argument, one family per row.
  Two inputs   the functions of two arguments a surface needs for a ridge,
               a valley or a polar radius.

There are no Greek letters or logic symbols: not one of them means anything
inside a surface expression, and a key that inserts something the parser
then rejects is worse than no key at all.

Each key is (label, inserted text, characters to step back afterwards) --
the step-back is what leaves the caret INSIDE the brackets of a function
that was just inserted, so `sin(` + `)` behaves like one keystroke.
"""

# Variables and constants; a numeric pad with the operations beside it;
# powers, roots and brackets on the right.
KEYS_NUMBERS = (
    (('x', 'x', 0), ('y', 'y', 0), ('u', 'u', 0), ('v', 'v', 0),
     ('π', 'pi', 0), ('e', 'e', 0), ('⌫', None, 0)),
    (('7', '7', 0), ('8', '8', 0), ('9', '9', 0), ('÷', '/', 0),
     ('(', '(', 0), (')', ')', 0), ('x²', '^2', 0)),
    (('4', '4', 0), ('5', '5', 0), ('6', '6', 0), ('×', '*', 0),
     ('√', 'sqrt()', 1), ('|x|', 'abs()', 1), ('xⁿ', '^', 0)),
    (('1', '1', 0), ('2', '2', 0), ('3', '3', 0), ('−', '-', 0),
     ('0', '0', 0), ('.', '.', 0), ('+', '+', 0)),
)

# One-argument functions, one family to a row: trigonometric; hyperbolic,
# exponential and logarithmic; then roots, absolute value and rounding.
KEYS_FUNCTIONS = (
    (('sin', 'sin()', 1), ('cos', 'cos()', 1), ('tan', 'tan()', 1),
     ('sin⁻¹', 'asin()', 1), ('cos⁻¹', 'acos()', 1), ('tan⁻¹', 'atan()', 1),
     ('⌫', None, 0)),
    (('sinh', 'sinh()', 1), ('cosh', 'cosh()', 1), ('tanh', 'tanh()', 1),
     ('eˣ', 'exp()', 1), ('ln', 'log()', 1), ('log₁₀', 'log10()', 1),
     ('log₂', 'log2()', 1)),
    (('√', 'sqrt()', 1), ('ⁿ√', '^(1/)', 1), ('10ˣ', '10^', 0),
     ('|x|', 'abs()', 1), ('⌊x⌋', 'floor()', 1), ('⌈x⌉', 'ceil()', 1),
     ('π', 'pi', 0)),
)

# Functions of two arguments -- the ones a surface actually needs for a
# ridge, a valley or a polar radius.
KEYS_TWO_INPUTS = (
    (('min', 'min(,)', 2), ('max', 'max(,)', 2), ('hypot', 'hypot(,)', 2),
     ('⌫', None, 0)),
    (('atan2', 'atan2(,)', 2), ('xʸ', 'pow(,)', 2), (',', ',', 0),
     ('π', 'pi', 0)),
)

TABS = (('Numbers', KEYS_NUMBERS), ('Functions', KEYS_FUNCTIONS),
        ('Two inputs', KEYS_TWO_INPUTS))

# The one key that does not insert: it deletes the character before the
# caret. Marked by a None insertion so the builder can wire it to a
# different handler without special-casing a label.
BACKSPACE = '⌫'
