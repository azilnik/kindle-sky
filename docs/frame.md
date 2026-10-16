# The frame

The Kindle sits in an IKEA RÖDALM 13×18 cm frame, held by two 3D-printed parts. The insert's
front is the mat you see, and its back is a pocket the Kindle snaps into. A back plate closes
it, flush with the frame's back edge, in place of the stock hardboard back.

<img alt="The back of the printed insert: a pocket the size of the Kindle, with snap lips on the long sides, spring tabs on the outer walls and a slot at the port end for the cable" src="images/insert-13x18.png" width="820">

## What to print

| Kindle | Insert | Back plate |
|---|---|---|
| Paperwhite 4 | [insert-rodalm13x18.3mf](../insert/insert-rodalm13x18.3mf) ([.stl](../insert/insert-rodalm13x18.stl)) | [plate-rodalm13x18.3mf](../insert/plate-rodalm13x18.3mf) ([.stl](../insert/plate-rodalm13x18.stl)) |
| Paperwhite 2 | [insert-rodalm13x18-pw2.3mf](../insert/insert-rodalm13x18-pw2.3mf) ([.stl](../insert/insert-rodalm13x18-pw2.stl)) | [plate-rodalm13x18-pw2.3mf](../insert/plate-rodalm13x18-pw2.3mf) ([.stl](../insert/plate-rodalm13x18-pw2.stl)) |

Each Kindle needs its own pair: the plate's spring fingers reach into pockets in the
insert's walls, and those sit in different places on the two.

- Print in PETG, with no brim or skirt. PLA works, but its springs relax over time.
- Print the insert face down, and the plate back face down with its fingers up.
- Both fit a 180 mm bed (a Bambu A1 mini). The 13×18 insert takes about 78 cm³ of filament
  for a Paperwhite 4 and 71 cm³ for a Paperwhite 2; a plate about 29 cm³.
- The insert leaves 10.5 mm (Paperwhite 4) or 11 mm (Paperwhite 2) beside the charging
  port for a right-angle plug. The cable and the power button stay reachable through the
  plate's slot at that end.
- Leave the stock back board and its tabs out. The insert's walls and the plate together
  fill the frame's 24 mm depth.

Both inserts are drawn from measured Kindles. The Paperwhite 4 pair is the one in the photos
and on the wall; the Paperwhite 2 insert has been test fitted.

## On a windowsill: solar backing (Paperwhite 2)

[solar-rodalm13x18-pw2.3mf](../insert/solar-rodalm13x18-pw2.3mf) ([.stl](../insert/solar-rodalm13x18-pw2.stl))
is the Paperwhite 2's back plate with a closed shell behind it that holds a small USB solar
panel at 60°, facing the window. Print it in place of the plate.

- Print it standing on its port end, with supports from the build plate only: the plate's
  bottom edge starts 2 mm above the bed.
- Measure your panel's thickness first and set `PANEL_T` at the top of
  [insert/solar.py](../insert/solar.py). The panel's other sizes come from the printed
  gauges in [insert/gauges.py](../insert/gauges.py).

## Other frames and parts

- **RÖDALM 21×30 cm:** [insert-rodalm21x30.3mf](../insert/insert-rodalm21x30.3mf) sits behind
  IKEA's own paper mat. It hasn't been built: measure the mat's opening first, and print it
  with supports, since its centering rim leaves the body overhanging by about 4 mm.
- **A back board** ([insert/backboard.py](../insert/backboard.py)) that copies the stock
  hardboard back with an opening over the port. It was drawn for an earlier, shallower
  insert and doesn't fit behind the current one; use the back plate.
- **A different frame:** add its size to `FRAMES` in [insert/insert.py](../insert/insert.py)
  and run it. The command, and every option, is at the top of that file. `--plate` makes the
  back plate, `--test` a quick fit-check strip.

## Measure what the mat hides

The mat covers the edges of the screen. `safe` in `config.json` tells the display which part
stays visible, as `[left, top, right, bottom]` in pixels. The configs that ship already fit
these inserts; measure again if your print or frame differs. The test pattern shows you the
numbers.

<img alt="The test pattern: a grid with heavy lines every 100 pixels labeled x100, x200 across and y100, y200 down, and a box in the middle explaining how to read it" src="images/test-pattern.png" width="520">

1. Press the Kindle's power button once to wake its Wi-Fi.
2. Run `tools/grid.sh` to put the pattern on the screen.
3. With the Kindle in its frame, read the first label or line you can see at each edge.
   Heavy lines are every 100 pixels, thin lines every 20. For example, two thin lines and
   then `x100` on the left edge means left is 60.
4. Put the four numbers in `safe` on the Kindle.
5. Run `tools/grid.sh check`. It draws a box at `safe`, and all four sides of it should be
   visible, right at the edge of the mat.
6. Run `tools/grid.sh done` to bring the sky back.

The dome and its lettering stay `inset` (12 pixels, 1 mm) inside `safe`.

<img alt="The frame showing the grid, so the visible area can be read off" src="images/calibration-grid.jpg" width="520">
