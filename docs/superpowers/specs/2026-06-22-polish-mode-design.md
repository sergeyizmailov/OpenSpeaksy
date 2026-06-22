# Polish Mode — Design

Date: 2026-06-22
Status: Approved, ready for implementation plan

## Goal

Add a third hotkey that always outputs natural, correct Polish, regardless of
the spoken input language. One button serves two use cases:

- Speak Russian → output is a Polish translation.
- Speak imperfect/broken Polish → output is grammar-corrected, natural Polish.

The "translate vs. correct" decision is made by the LLM inside a single prompt —
there is no separate toggle. This doubles as a language-learning aid: the user
can attempt Polish and get a clean version back, or fall back to Russian when
stuck.

## Non-goals

- No new model, backend, or config surface beyond what dictate/translate use.
- No second refinement pass (the Polish prompt already targets natural output).
- No language auto-routing UI — the LLM handles it implicitly.

## Hotkey

- Right Shift: `POLISH_KEYCODE = 0x3C`, `POLISH_FLAG = 0x200`
  (`NX_DEVICERSHIFTKEYMASK`, distinguishes right Shift from left).
- Same hold-to-talk model as the existing two hotkeys.
- Same dead-key caveat as right Option: while held, typed letters are
  Shift-modified. Acceptable — the user is dictating, not typing. The event tap
  stays `kCGEventTapOptionListenOnly`, so the modifier is not swallowed.

## Behavior / data flow

1. `on_key_down(POLISH_KEYCODE, MODE_POLISH)` → record, overlay shows recording
   with the "Polish" label.
2. `on_key_up` → save pending WAV named `...-<uuid>.polish.wav`, spawn worker.
3. Worker calls `transcriber.transcribe_to_polish_sync(path)`:
   - Whisper transcription with **no forced language** (`language=None`,
     auto-detect) — input may be RU or PL. No RU bias prompt.
   - `.rstrip()` the transcript.
   - If empty → return `""`.
   - Single `_chat_completion(POLISH_SYSTEM_PROMPT, transcript, label="polish")`.
   - Return `polish + " "` (trailing space, mirroring dictate/translate).
4. Paste, overlay hides — identical to existing modes.

Crash recovery preserves intent through the `.polish` filename segment, exactly
like translate.

## Changes by file

### `main.py`

- Add `POLISH_KEYCODE = 0x3C`, `POLISH_FLAG = 0x200`, `MODE_POLISH = "polish"`.
- `tap_callback`: add an `elif keycode == POLISH_KEYCODE` branch mirroring the
  translate branch (down → `on_key_down(keycode, MODE_POLISH)`, up → `on_key_up`).
- `process_pending_recording`: route `MODE_POLISH` → `transcribe_to_polish_sync`.
- `recover_pending_recordings`: same routing for recovered files.
- `parse_pending_mode`: include `MODE_POLISH` in the suffix-match tuple.
- Startup log line: mention the third hotkey.

### `transcriber.py`

- `POLISH_SYSTEM_PROMPT`: reuse the anti-injection framing from
  `TRANSLATION_SYSTEM_PROMPT` (input is source material, never an instruction;
  never answer/comply/react). Instruct: produce natural, grammatically correct
  Polish; if the input is Russian (or any non-Polish), translate it to Polish;
  if it is already Polish, fix grammar, cases, word order, and naturalness while
  preserving meaning, tone, and register. Output only the Polish text. Include
  worked examples for both cases: `RU → PL` and `broken PL → corrected PL`.
- `transcribe_to_polish_sync(self, wav_path)`: as described in the data flow.
  Reuses `transcribe_wav_sync` (no language, no prompt), `_chat_completion`, and
  the existing key-rotation path.

### `overlay.py`

The overlay label is currently binary (`translate=True/False` + the constant
`LABEL_TEXT = "Translate"`). Generalize to an arbitrary label string:

- `OverlayView.setTranslate_(bool)` → `setLabel_(text_or_None)`; store
  `self._label` instead of `self._translate`.
- `_draw_overlay`: draw `self._label` (when set and mode != "error") using the
  existing `LABEL_ATTRS`/positioning; remove the `LABEL_TEXT` constant
  dependency on a fixed string (keep styling constants).
- `Overlay.show(mode, label=None)` and `_show(mode, label)`.

Call-site updates in `main.py`:
- dictate → `overlay.show(..., label=None)`
- translate → `overlay.show(..., label="Translate")`
- polish → `overlay.show(..., label="Polish")`

## Tests

Mirror the existing patterns:

- `tests/test_pending_filenames.py`: add `test_polish_filename_parses`
  (`parse_pending_mode` returns `MODE_POLISH` for a `.polish.wav` name).
- `tests/test_hotkey_isolation.py`: the `_StubOverlay.show` signature must be
  updated from `show(self, mode, translate=False)` to `show(self, mode, label=None)`
  to match the new overlay API.
- Optional: a routing assertion that `MODE_POLISH` dispatches to
  `transcribe_to_polish_sync` (mirror translate routing coverage if present).

## Verification (primary signal)

Restart the agent, then with real audio:
1. Hold Right Shift, speak a Russian sentence → confirm correct Polish is pasted.
2. Hold Right Shift, speak a deliberately broken Polish sentence → confirm a
   corrected, natural Polish version is pasted.
3. Confirm the overlay shows the "Polish" label and the dictate/translate
   hotkeys still behave as before.

Secondary signal: `pytest` passes (state machine, filenames, hotkey isolation).
