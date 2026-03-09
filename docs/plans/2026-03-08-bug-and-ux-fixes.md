# Bug and UX Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all identified bugs and UI/UX issues from the workspace audit across `main.py`, `ui/tooltip.py`, `ui/settings_dialog.py`, `ui/progress_dialog.py`, and `core/audio_analyzer.py`.

**Architecture:** Each task is a focused, self-contained edit to one file or one concern. No new dependencies needed — all fixes use stdlib threading primitives, existing PyQt5 APIs, and `functools.partial`. Test each fix by running the app and triggering the relevant code path.

**Tech Stack:** Python 3, PyQt5, threading, functools

---

## Task 1: Replace bare `except:` in `progress_dialog.py`

**Files:**
- Modify: `ui/progress_dialog.py:80`

**Step 1: Make the change**

In `_init_ui`, replace:
```python
        except:
            # Fallback to simple layout without spinner
            pass
```
with:
```python
        except Exception:
            # Fallback to simple layout without spinner — spinner resource not embedded
            pass
```

**Step 2: Verify**
Run the app. Progress dialog should appear normally.

**Step 3: Commit**
```bash
git add ui/progress_dialog.py
git commit -m "fix: replace bare except in progress_dialog spinner loading"
```

---

## Task 2: Replace bare `except:` in `main.py`

**Files:**
- Modify: `main.py:520, 1017, 1557`

**Step 1: Make the changes**

At line 520 (hotkey removal in `setup_hotkeys`), replace:
```python
                except:
                    pass
```
with:
```python
                except Exception:
                    pass
```

At line 1017 (error dialog fallback in `analyze_file`), replace:
```python
            except:
                pass  # If even showing the error fails, just continue
```
with:
```python
            except Exception:
                pass  # If even showing the error fails, just continue
```

At line 1557 (hotkey removal in `track_input`), replace:
```python
                except:
                    pass
```
with:
```python
                except Exception:
                    pass
```

Search for any remaining bare `except:` in `main.py` using grep and fix them the same way.

**Step 2: Verify**
```bash
grep -n "except:" main.py
```
Expected: no results.

**Step 3: Commit**
```bash
git add main.py
git commit -m "fix: replace all bare except clauses in main.py"
```

---

## Task 3: Add `threading.Lock` to protect `detection_active` flag

**Files:**
- Modify: `main.py`

**Step 1: Add lock initialization**

Find `__init__` of `AudioTooltipApp` (around line 100). After `self.detection_active = False`, add:
```python
        self._detection_lock = threading.Lock()
```

**Step 2: Replace unprotected flag checks in `track_input` (around lines 1541-1550)**

Replace:
```python
            if not self.detection_active:
                try:
                    self.detection_active = True
                    detection_thread = threading.Thread(target=self.check_file_under_cursor)
                    detection_thread.daemon = True
                    detection_thread.start()
                except Exception as e:
                    self.module_logger.error(f"Error in hotkey handler: {e}")
                    self.module_logger.error(traceback.format_exc())
                    self.detection_active = False
```
with:
```python
            with self._detection_lock:
                if self.detection_active:
                    return
                self.detection_active = True
            try:
                detection_thread = threading.Thread(target=self.check_file_under_cursor)
                detection_thread.daemon = True
                detection_thread.start()
            except Exception as e:
                self.module_logger.error(f"Error in hotkey handler: {e}")
                self.module_logger.error(traceback.format_exc())
                with self._detection_lock:
                    self.detection_active = False
```

Apply the same lock pattern to the middle-click detection block (around lines 1583-1591).

Also apply to `trigger_detection` (around line 1612):
```python
    def trigger_detection(self):
        self.module_logger.info("Two-finger tap detected, initiating detection")
        with self._detection_lock:
            if self.detection_active:
                return
            self.detection_active = True
        detection_thread = threading.Thread(target=self.detect_audio_file)
        detection_thread.daemon = True
        detection_thread.start()
```

Make sure `check_file_under_cursor` and `detect_audio_file` reset the flag inside `finally` blocks (they already do at lines 1522 and equivalent). Keep those as-is but wrap the assignment:
```python
        finally:
            with self._detection_lock:
                self.detection_active = False
```

**Step 3: Verify**
Run app, trigger hotkey multiple times rapidly. Only one detection thread should run at a time (check logs).

**Step 4: Commit**
```bash
git add main.py
git commit -m "fix: add threading.Lock to protect detection_active flag from race condition"
```

---

## Task 4: Fix lambda signal connections — prevent memory leaks

**Files:**
- Modify: `main.py:966-972`

**Step 1: Add import at top of file** (if not already present)

At the top of `main.py`, ensure:
```python
from functools import partial
```

**Step 2: Replace lambda captures in `analyze_file`**

Replace:
```python
                    worker.finished.connect(
                        lambda result: self.handle_analysis_result(result, file_path, channel))
                    worker.progress.connect(
                        lambda msg: self.showProgressSignal.emit(msg))
                    worker.error.connect(self.handle_worker_error)
                    worker.finished.connect(
                        lambda: self.cleanup_worker(worker))  # Clean up when done
```
with:
```python
                    worker.finished.connect(
                        partial(self.handle_analysis_result, file_path=file_path, channel=channel))
                    worker.progress.connect(self.showProgressSignal.emit)
                    worker.error.connect(self.handle_worker_error)
                    worker.finished.connect(partial(self.cleanup_worker, worker))
```

Note: `handle_analysis_result` signature is `(self, result, file_path, channel)` — `partial` will pass `result` as first positional arg, `file_path` and `channel` as keyword args. Verify the method signature matches; adjust if needed.

**Step 3: Also fix `on_visualization_requested` (line 1111)**

Replace:
```python
        worker.finished.connect(lambda: self.hideProgressSignal.emit())
```
with:
```python
        worker.finished.connect(self.hideProgressSignal.emit)
```

**Step 4: Verify**
Analyze several files in sequence. Memory should not grow unboundedly (check via Task Manager or add `len(self.workers)` log after cleanup).

**Step 5: Commit**
```bash
git add main.py
git commit -m "fix: replace lambda signal connections with partial to prevent memory leaks"
```

---

## Task 5: Fix generic error dialog — avoid leaking sensitive info

**Files:**
- Modify: `main.py:1012-1016`

**Step 1: Replace**

```python
                QMessageBox.critical(
                    None,
                    "Critical Error",
                    f"An unexpected error occurred:\n{str(e)}\n\nSee logs for details."
                )
```
with:
```python
                QMessageBox.critical(
                    None,
                    "Critical Error",
                    "An unexpected error occurred. See application logs for details."
                )
```

**Step 2: Commit**
```bash
git add main.py
git commit -m "fix: remove exception detail from critical error dialog to prevent info disclosure"
```

---

## Task 6: Normalize settings reads to typed values

**Files:**
- Modify: `main.py`

The pattern `self.settings.value("use_whole_signal", "false") == "true"` and `int(self.settings.value("preview_duration", "10"))` are scattered. Wrap them in a helper.

**Step 1: Add helper methods to `AudioTooltipApp`**

Add after `load_default_settings`:
```python
    def _setting_bool(self, key: str, default: bool = False) -> bool:
        """Read a boolean setting stored as 'true'/'false' string."""
        return self.settings.value(key, "true" if default else "false") == "true"

    def _setting_int(self, key: str, default: int = 0) -> int:
        """Read an integer setting stored as a string."""
        try:
            return int(self.settings.value(key, str(default)))
        except (ValueError, TypeError):
            return default
```

**Step 2: Replace raw settings reads in `on_visualization_requested` (lines 1097-1101)**

Replace:
```python
        use_whole_signal = self.settings.value(
            "use_whole_signal", "false") == "true"
        preview_duration = - \
            1 if use_whole_signal else int(
                self.settings.value("preview_duration", "10"))
```
with:
```python
        use_whole_signal = self._setting_bool("use_whole_signal", False)
        preview_duration = -1 if use_whole_signal else self._setting_int("preview_duration", 10)
```

**Step 3: Find all other raw `self.settings.value(` reads in `main.py` that cast to int/bool and apply helpers.**

Run:
```bash
grep -n 'settings.value' main.py
```
Fix each occurrence following the same pattern.

**Step 4: Commit**
```bash
git add main.py
git commit -m "fix: add typed settings helpers to prevent type-mismatch bugs"
```

---

## Task 7: Validate `currentData()` before using in transcription

**Files:**
- Modify: `ui/tooltip.py:830`

**Step 1: Add validation in `_run_transcription`**

Replace:
```python
        # Get selected channel
        selected_channel = self.transcription_channel_combo.currentData()

        # If "Current Channel" is selected, use the current channel
        if selected_channel == -2:
            selected_channel = self.current_channel
```
with:
```python
        # Get selected channel (guard against empty combo box)
        selected_channel = self.transcription_channel_combo.currentData()
        if selected_channel is None:
            selected_channel = self.current_channel
        elif selected_channel == -2:
            selected_channel = self.current_channel
```

**Step 2: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: guard against None currentData() in transcription channel combo"
```

---

## Task 8: Truncate long file paths in title bar labels

**Files:**
- Modify: `ui/tooltip.py:1122-1124`

**Step 1: Add helper method to `EnhancedTooltip`**

Add before `update_content`:
```python
    @staticmethod
    def _elide_path(path: str, max_len: int = 80) -> str:
        """Shorten a path to max_len chars, keeping filename visible."""
        if len(path) <= max_len:
            return path
        head, tail = os.path.split(path)
        # Keep filename; shorten directory
        keep_tail = tail
        prefix = ".../"
        allowed = max_len - len(keep_tail) - len(prefix)
        if allowed < 4:
            return prefix + keep_tail
        return prefix + head[-allowed:] + "/" + keep_tail
```

**Step 2: Apply in `update_content`**

Replace:
```python
        file_name = os.path.basename(file_path)
        self.title_label.setText(f"Audio Analysis: {file_name}")
        self.file_name_label.setText(f"File: {file_path}")
```
with:
```python
        file_name = os.path.basename(file_path)
        self.title_label.setText(f"Audio Analysis: {file_name}")
        self.file_name_label.setText(f"File: {self._elide_path(file_path)}")
        self.file_name_label.setToolTip(file_path)  # Full path on hover
```

**Step 3: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: truncate long file paths in tooltip labels, show full path as tooltip"
```

---

## Task 9: Add "Save All" overwrite confirmation

**Files:**
- Modify: `ui/tooltip.py:358-432`

**Step 1: Collect paths before writing, check for existence**

In `_save_all`, after building the list of items to save (before the first `open()` call), add a check:

Replace the block starting at line 371 with:
```python
        # Build list of planned save paths
        planned = []
        if self.metadata_label.text() and self.metadata_label.text() != "No metadata available":
            planned.append(os.path.join(directory, f"{base_name}{channel_suffix}_metadata.txt"))
        if self.transcript_text.text() and self.transcript_text.text() != "No transcription available":
            planned.append(os.path.join(directory, f"{base_name}_transcript.txt"))
        if self.waveform_label.pixmap() and not self.waveform_label.pixmap().isNull():
            planned.append(os.path.join(directory, f"{base_name}{channel_suffix}_waveform.png"))
        if (self.viz_display.pixmap() and not self.viz_display.pixmap().isNull() and
                hasattr(self, '_viz_generated') and self._viz_generated):
            viz_type = self.viz_combo_menu.text().lower().replace('-', '_')
            planned.append(os.path.join(directory, f"{base_name}{channel_suffix}_{viz_type}.png"))

        if not planned:
            QMessageBox.warning(self, "Nothing to Save", "No content available to save.")
            return

        # Check for existing files
        existing = [p for p in planned if os.path.exists(p)]
        if existing:
            names = "\n".join(os.path.basename(p) for p in existing)
            reply = QMessageBox.question(
                self, "Overwrite Files?",
                f"The following files already exist and will be overwritten:\n\n{names}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
```

Then proceed with the actual save operations (keep existing try/except save blocks, just remove the duplicate `planned` variable computation at top).

**Step 2: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: add overwrite confirmation dialog in Save All to prevent data loss"
```

---

## Task 10: Add cancel support to progress dialog for transcription

**Files:**
- Modify: `main.py` (where `ProgressDialog` is created for transcription)
- Modify: `ui/progress_dialog.py` (already has `cancelable` param — just wire it)

The `ProgressDialog` already accepts `cancelable=True` (line 27 of `progress_dialog.py`). The cancel button calls `self.reject()`. We need to:
1. Show the dialog with `cancelable=True` for transcription operations.
2. Connect `rejected` signal to cancel the worker.

**Step 1: Find where progress dialog is shown for transcription**

Search in main.py:
```bash
grep -n "showProgressSignal\|ProgressDialog\|transcri" main.py | head -40
```

**Step 2: Make `AudioTooltipWorker` cancellable**

In the worker class (search for `class AudioTooltipWorker`), add a cancel flag:
```python
    def cancel(self):
        self._cancelled = True
```

In `run()`, check `self._cancelled` periodically (before each major step).

**Step 3: Wire cancel in `analyze_file`**

When the progress dialog is shown (via `showProgressSignal`), after showing it, connect:
```python
        # For transcription-heavy analysis, make dialog cancelable
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.cancelable = True
            if hasattr(self.progress_dialog, 'cancel_button'):
                pass  # already wired to reject()
            self.progress_dialog.rejected.connect(
                lambda: worker.cancel() if hasattr(worker, 'cancel') else None)
```

**Step 4: Commit**
```bash
git add main.py ui/progress_dialog.py
git commit -m "feat: add cancel support for long-running analysis operations"
```

---

## Task 11: Show loading indicator when switching channels

**Files:**
- Modify: `ui/tooltip.py`

**Step 1: Add a loading overlay label**

In `__init__` of `EnhancedTooltip`, after creating `self.tab_widget`, add:
```python
        # Overlay label shown while re-analysis is in progress
        self._loading_label = QLabel("Loading...", self)
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._loading_label.setStyleSheet(
            "background: rgba(255,255,255,180); color: #333; font-size: 14px; font-weight: bold;")
        self._loading_label.hide()
```

**Step 2: Add show/hide methods**

```python
    def show_loading(self):
        """Show loading overlay over the content area."""
        self._loading_label.setGeometry(self.tab_widget.geometry())
        self._loading_label.raise_()
        self._loading_label.show()

    def hide_loading(self):
        """Hide loading overlay."""
        self._loading_label.hide()
```

**Step 3: Call from main app**

In `main.py`, in `on_channel_changed` callback:
```python
    def on_channel_changed(self, channel):
        self.tooltip.show_loading()
        self.analyze_file(self.tooltip.current_file, channel)
```

In `handle_analysis_result`, before updating tooltip:
```python
        self.tooltip.hide_loading()
```

**Step 4: Commit**
```bash
git add ui/tooltip.py main.py
git commit -m "feat: show loading overlay when switching channels to indicate re-analysis"
```

---

## Task 12: Check Audacity availability and reflect in button state

**Files:**
- Modify: `ui/tooltip.py:216-301`

**Step 1: Add an Audacity check method**

```python
    @staticmethod
    def _find_audacity() -> str | None:
        """Return path to Audacity executable, or None if not found."""
        if os.name == 'nt':
            candidates = [
                os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Audacity', 'Audacity.exe'),
                os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Audacity', 'Audacity.exe'),
                r'C:\Program Files\Audacity\Audacity.exe',
                r'C:\Program Files (x86)\Audacity\Audacity.exe',
            ]
            return next((p for p in candidates if os.path.exists(p)), None)
        return None
```

**Step 2: Update button on creation**

In `_create_action_buttons`, after creating `audacity_button`:
```python
        audacity_path = self._find_audacity()
        if audacity_path:
            audacity_button.setToolTip(f"Open in Audacity ({audacity_path})")
        else:
            audacity_button.setToolTip("Audacity not found — will open with system default player")
            audacity_button.setStyleSheet("color: #888;")  # Gray out visually
```

**Step 3: Simplify `_open_in_audacity` to use the helper**

Replace the path-detection logic in `_open_in_audacity` with a call to `self._find_audacity()`.

**Step 4: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: check Audacity availability at startup and reflect in button tooltip/style"
```

---

## Task 13: Make metadata label scrollable

**Files:**
- Modify: `ui/tooltip.py` (wherever `metadata_label` is added to layout in the Overview tab)

**Step 1: Find where metadata_label is placed**

Search: `grep -n "metadata_label" ui/tooltip.py`

**Step 2: Wrap in a `QScrollArea`**

Instead of adding `self.metadata_label` directly to layout, wrap it:
```python
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.setMaximumHeight(150)
        metadata_scroll.setWidget(self.metadata_label)
        metadata_scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(metadata_scroll)
```

Remove the direct `layout.addWidget(self.metadata_label)` if present.

**Step 3: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: wrap metadata label in scroll area to prevent overflow"
```

---

## Task 14: Add missing tooltips to action buttons

**Files:**
- Modify: `ui/tooltip.py:202-231`

**Step 1: Add tooltips**

After creating each button without a tooltip, add:
```python
        self.play_button.setToolTip("Play a short audio preview of the file")
        audacity_button.setToolTip("Open the audio file in Audacity (or system default player)")
        save_button.setToolTip("Save analysis results (metadata, waveform, visualization, transcript) to files")
```

(Refresh button already has a tooltip at line 213.)

**Step 2: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: add missing tooltips to Play Preview and Save All buttons"
```

---

## Task 15: Fix visualization scaling to be DPI-aware

**Files:**
- Modify: `ui/tooltip.py:319-341`

**Step 1: Replace hardcoded sizes**

Replace:
```python
        # At least 3x wider, minimum 1200px
        expanded_width = max(orig_width * 3, 1200)
        # At least 3x taller, minimum 900px
        expanded_height = max(orig_height * 3, 900)
```
with:
```python
        # Scale to 80% of available screen space, maintaining aspect ratio
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        expanded_width = min(max(orig_width * 3, 800), int(screen.width() * 0.85))
        expanded_height = min(max(orig_height * 3, 600), int(screen.height() * 0.85))
```

**Step 2: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: make visualization expand dialog size responsive to screen resolution"
```

---

## Task 16: Improve empty transcription reason message

**Files:**
- Modify: `ui/tooltip.py` (where transcription text is set to placeholder)

**Step 1: Find placeholder assignment**

Search: `grep -n "No transcription available" ui/tooltip.py`

**Step 2: Replace with context-aware messages**

In `update_content`, where transcription is updated, replace the simple fallback with:
```python
        if transcription:
            self.transcript_text.setText(transcription)
        else:
            # Distinguish between "disabled" and "no speech detected"
            transcription_enabled = (
                self.settings.value("enable_transcription", "false") == "true"
                if self.settings else False
            )
            if transcription_enabled:
                self.transcript_text.setText(
                    "No speech detected in this audio segment.\n\n"
                    "Tip: Try using a longer preview duration in Settings."
                )
            else:
                self.transcript_text.setText(
                    "Transcription is disabled.\n\n"
                    "Enable it in Settings → Transcription and provide Azure credentials."
                )
```

**Step 3: Commit**
```bash
git add ui/tooltip.py
git commit -m "fix: show context-aware reason when transcription result is empty"
```

---

## Task 17: Clarify "Same as preview duration" transcription option

**Files:**
- Modify: `ui/settings_dialog.py:242-243`

**Step 1: Update item label**

Replace:
```python
        self.transcription_duration_combo.addItem(
            "Same as preview duration", "preview")
```
with:
```python
        self.transcription_duration_combo.addItem(
            "Same as preview duration (set in Analysis tab)", "preview")
```

**Step 2: Commit**
```bash
git add ui/settings_dialog.py
git commit -m "fix: clarify transcription duration 'same as preview' option label"
```

---

## Task 18: Fix auto-hide — show visual countdown warning

**Files:**
- Modify: `ui/tooltip.py`

**Step 1: Add countdown label to title bar**

In `_create_title_bar`, after the close button:
```python
        self._countdown_label = QLabel("")
        self._countdown_label.setStyleSheet("color: #999; font-size: 9px;")
        self._countdown_label.setToolTip("Tooltip will auto-hide. Click pin to prevent.")
        title_layout.addWidget(self._countdown_label)
```

**Step 2: Add a countdown update timer**

In `__init__`, after `self.auto_hide_timer`:
```python
        self._countdown_tick = QTimer(self)
        self._countdown_tick.setInterval(1000)
        self._countdown_tick.timeout.connect(self._update_countdown)
        self._remaining_seconds = 0
```

**Step 3: Wire into `reset_auto_hide_timer`**

```python
    def reset_auto_hide_timer(self):
        if self.pinned:
            return
        if self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()
        self._countdown_tick.stop()
        self._remaining_seconds = self.auto_hide_seconds
        self._update_countdown()
        self._countdown_tick.start()
        self.auto_hide_timer.start(self.auto_hide_seconds * 1000)

    def _update_countdown(self):
        if self._remaining_seconds > 0:
            self._countdown_label.setText(f"⏱ {self._remaining_seconds}s")
            self._remaining_seconds -= 1
        else:
            self._countdown_label.setText("")
            self._countdown_tick.stop()
```

**Step 4: Stop countdown on pin**

In `_toggle_pin`:
```python
        if checked:
            if self.auto_hide_timer.isActive():
                self.auto_hide_timer.stop()
            self._countdown_tick.stop()
            self._countdown_label.setText("")
```

**Step 5: Commit**
```bash
git add ui/tooltip.py
git commit -m "feat: add visual countdown in title bar before auto-hide"
```

---

## Task 19: Final verification pass

**Step 1: Run the application**
```bash
python main.py
```

**Step 2: Check for remaining bare excepts**
```bash
grep -n "except:" main.py ui/tooltip.py ui/settings_dialog.py ui/progress_dialog.py core/audio_analyzer.py utils/file_utils.py
```
Expected: no results.

**Step 3: Manually test key flows**
- Open the app and analyze an audio file
- Switch channels → loading overlay appears
- Hover over file_name_label → full path shown in tooltip
- Click Save All on a file where outputs already exist → confirmation dialog appears
- Check the transcription tab with transcription disabled → contextual message shown
- Let auto-hide run → countdown appears in title bar
- Click pin → countdown disappears and timer stops

**Step 4: Commit any final tweaks**
```bash
git add -A
git commit -m "fix: final verification tweaks after audit fixes"
```
