# Author: Nicolas Legrand <nicolas.legrand@cfin.au.dk>

import functools
import json
from os import PathLike
from pathlib import Path
from typing import List, Optional, Tuple, Union

import ipywidgets as widgets
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import date2num
from matplotlib.widgets import SpanSelector

from systole.detection import ecg_peaks, ppg_peaks, rsp_peaks
from systole.plots import plot_raw
from systole.utils import ecg_strings, norm_bad_segments, ppg_strings, resp_strings


class Viewer:
    """This class handles the interaction with BIDS structured folders. It calls
    the` Editor` class internally to generate the interactive plots.

    Parameters
    ----------
    bids_folder :
        Path to the input BIDS folder. If the BIDS folder is used as input, the `Viewer`
        tries to read the preprocessed physiological recordings generated by the
        command line for reports in `BIDS/derivatives/systole/`.
        .. note::
            If this parameter is provided, `preprocessed_folder` will be ignored
            (implicitely here, `preprocessed_folder=BIDS/derivatives/systole/`).
    preprocessed_folder :
        Path to the folder where preprocessed physiological recording have been saved.
        This should be used if not working directly inside the BIDS folder and the
        preprocessed data have been save loaclly.
        .. note::
            If this parameter is provided, `bids_folder` will be ignored.
    output_folder :
        Path to the output folder. This is where the JSON files containing peaks
        correction, bad segments and signal validity logs will be saved. If an empty
        strimg is provided (default), the results will be saved in
        `BIDS/derivative/systole/corrected/` when working in the BIDS folder, or in
        `preprocessed_folder/corrected/` when working whith a local folder.
    session :
        The BIDS sub-session where the pysio files are stored. Defaults to
        `"ses-session1"`.
    modality :
        The BIDS sub-modality where the pysio files are stored (e.g. `"func"` or
        `"beh"`).
    pattern :
        The string pattern that the pysio files should contain. This allows to refine
        the selection of possible physio files, in case the folders contains many
        `_physio-gz.tsv`.
    participant_id :
        The participant ID as registered in the BIDS folder. If `None` (default), the
        first participant in the list of available recordings is selected.
    signal_type :
       The type of signal that are being analyzed. Can be `"PPG"`, `"ECG"` or `"RESP"`.
       Defaults to `"PPG"`.
    figsize :
        The size of the interactive Matplotlib figure for peaks edition. Defaults to
        `(15, 7)`.

    See also
    --------
    Editor

    Raises
    ------
    ValueError
        If both `bids_folder` and `preprocessed_folder` are provided.

    """

    def __init__(
        self,
        bids_folder: Optional[Union[str, PathLike]] = None,
        preprocessed_folder: Optional[Union[str, PathLike]] = None,
        output_folder: Union[str, PathLike] = "",
        session: Union[str, PathLike] = "ses-session1",
        modality: Union[str, PathLike] = "beh",
        pattern: Union[str, PathLike] = "task-",
        participant_id: Optional[str] = None,
        signal_type: Union[str, PathLike] = "PPG",
        figsize: Tuple[int, int] = (15, 7),
    ) -> None:
        self.figsize = figsize

        if bids_folder is not None:
            self.bids_folder = bids_folder
            if not Path(bids_folder, "derivatives", "systole").exists():
                print(f"The BIDS folder {bids_folder} does not contains derivatives.")
            else:
                self.preprocessed_folder = Path(bids_folder)
        else:
            self.bids_folder = ""
            self.preprocessed_folder = preprocessed_folder  # type: ignore

        ##################
        # Create widgets #
        ##################
        self.bids_folder_ = widgets.Textarea(
            value=str(self.bids_folder),
            placeholder="Type something",
            description="BIDS folder:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )
        self.preprocessed_folder_ = widgets.Textarea(
            value=str(self.preprocessed_folder),
            placeholder="Type something",
            description="Preprocessed folder:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )
        self.session_ = widgets.Textarea(
            value=session,
            placeholder="Type something",
            description="Session:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )
        self.modality_ = widgets.Textarea(
            value=modality,
            placeholder="Type something",
            description="Modality:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )
        self.pattern_ = widgets.Textarea(
            value=pattern,
            placeholder="Type something",
            description="Pattern:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )
        self.signal_type_ = widgets.Dropdown(
            options=["PPG", "ECG", "RESP"],
            value=signal_type,
            description="Signal:",
            layout=widgets.Layout(width="250px"),
        )
        self.output_folder_ = widgets.Textarea(
            value=output_folder,
            placeholder="Type something",
            description="Output:",
            disabled=False,
            layout=widgets.Layout(width="250px"),
        )

        # Update the participant list from the BIDS parameters
        try:
            # Get the list of all participant from the folders
            self.participants_list = [
                f.stem
                for f in list(Path(self.preprocessed_folder_.value).glob("sub-*/"))
            ]
            if self.participants_list:
                self.participants_list.sort()

            # Filter participants that have no physio recording
            filter_participants_list = [
                part
                for part in self.participants_list
                if any(
                    Path(
                        self.preprocessed_folder_.value,
                        part,
                        self.session_.value,
                        self.modality_.value,
                    ).glob(f"*{self.pattern_.value}*.tsv.gz")
                )
            ]
            if len(filter_participants_list) == 0:
                print(
                    "No file is matching the given paterns.\n"
                    f"... Preprocessed folder: {self.preprocessed_folder_.value}\n"
                    f"... Session: {self.session_.value}\n"
                    f"... Modality: {self.modality_.value}\n"
                    f"... Pattern: {self.pattern_.value}"
                )
                self.participants_list = ["sub-"]
            else:
                self.participants_list = filter_participants_list
        except FileNotFoundError:
            print("Directory not found.")
            self.participants_list = ["sub-"]

        if participant_id is None:
            self.participant_id = self.participants_list[0]

        self.participants_ = widgets.Dropdown(
            options=self.participants_list,
            value=self.participant_id,
            description="Participant ID",
            layout=widgets.Layout(width="200px"),
        )

        # Keep updated if dropdown menus are used
        self.bids_folder_.observe(self.update_list, names="value")
        self.preprocessed_folder_.observe(self.update_list, names="value")
        self.session_.observe(self.update_list, names="value")
        self.modality_.observe(self.update_list, names="value")
        self.pattern_.observe(self.update_list, names="value")
        self.signal_type_.observe(self.plot_signal, names="value")
        self.participants_.observe(self.plot_signal, names="value")

        # Show the navigator and main plot
        self.io_box = widgets.VBox(
            [
                widgets.HBox(
                    [
                        self.bids_folder_,
                        self.preprocessed_folder_,
                        self.session_,
                        self.participants_,
                        self.modality_,
                    ]
                ),
                widgets.HBox([self.pattern_, self.signal_type_, self.output_folder_]),
            ]
        )

        self.output = widgets.Output()

        # Plot the first pysio file if any
        self.plot_signal(change=None)

    def update_list(self, change):
        """Updating the list of participants available in the folder when the text
        boxes are used."""

        self.participants_list = [
            f.stem for f in list(Path(self.bids_path.value).glob("sub-*/"))
        ]
        self.participants_list = [
            part
            for part in self.participants_list
            if any(
                Path(
                    self.bids_path.value,
                    self.participants_.value,
                    self.session_.value,
                    self.modality_.value,
                ).glob(f"*{self.pattern_.value}*.tsv.gz")
            )
        ]

        self.participants_.option = self.participants_list

    def plot_signal(self, change):
        # Load the physio files and store parameters in the Viewer class
        # then load the signal from the physio file and perform peaks detection
        self = self.load_file().load_signal()

        self.output.clear_output()
        with self.output:
            # Start the interactive editor for peaks correction
            self.editor = Editor(
                signal=self.input_signal,
                sfreq=1000,
                corrected_json=self.corrected_json,
                signal_type=self.signal_type_.value,
                figsize=self.figsize,
                corrected_peaks=self.corrected_peaks,
                bad_segments=self.bad_segments,
                viewer=self,
            )
            plt.show()

    def load_signal(self):
        """Load the signal from the input folder (BIDS or local)."""

        # In case no file was match the requirements
        if self.physio_file is None:
            return self

        self.physio_df = None
        self.input_signal = None
        self.corrected_peaks = None
        self.bad_segments = None

        # Load the physiological signal from the BIDS/preprocessed folder
        self.physio_df = pd.read_csv(
            self.physio_file,
            sep="\t",
            compression="gzip",
            names=self.input_columns_names,
        )
        self.physio_df.columns = self.physio_df.columns.str.lower()

        # Path to the corrected JSON files (if the signal has already been checked)
        if self.bids_folder is None:
            self.corrected_json = Path(
                self.preprocessed_folder,
                "corrected",
                str(self.participants_.value),
                str(self.session_.value),
                self.modality_.value,
                f"{self.physio_file.stem[:-11]}_corrected.json",
            )
        else:
            # When reading the raw data directly, the JSON file
            # must be loaded from the derivatives
            self.corrected_json = Path(
                self.preprocessed_folder,
                "derivatives",
                "systole",
                "corrected",
                str(self.participants_.value),
                str(self.session_.value),
                self.modality_.value,
                f"{self.physio_file.stem[:-11]}_corrected.json",
            )

        if self.signal_type_.value.lower() == "ecg":
            ecg_col = [col for col in self.physio_df.columns if col in ecg_strings]
            ecg_col = ecg_col[0] if len(ecg_col) > 0 else None

            self.input_signal = self.physio_df[ecg_col].to_numpy()
            print(f"Loading electrocardiogram - sfreq={self.sfreq} Hz.")

        elif self.signal_type_.value.lower() == "ppg":
            ppg_col = [col for col in self.physio_df.columns if col in ppg_strings]
            ppg_col = ppg_col[0] if len(ppg_col) > 0 else None

            self.input_signal = self.physio_df[ppg_col].to_numpy()
            print(f"Loading photoplethysmogram - sfreq={self.sfreq} Hz.")

        elif self.signal_type_.value.lower() == "resp":
            res_col = [col for col in self.physio_df.columns if col in resp_strings]
            res_col = res_col[0] if len(res_col) > 0 else None

            self.input_signal = self.physio_df[res_col].to_numpy()
            print(f"Loading respiratory signal - sfreq={self.sfreq} Hz.")

        # Resample the input signal to fit with the peaks vector
        if self.sfreq is not None:
            time = np.arange(0, len(self.input_signal) / self.sfreq, 1 / self.sfreq)
            new_time = np.arange(0, len(self.input_signal) / self.sfreq, 1 / 1000)
            self.input_signal = np.interp(new_time, time, self.input_signal)

        # Load peaks, bad segments and reject signal from the JSON logs
        if self.corrected_json.exists():
            # Opening JSON file and extract metadata
            f = open(self.corrected_json)
            json_data = json.load(f)

            self.bad_segments = json_data[self.signal_type_.value.lower()][
                "bad_segments"
            ]

            # If corrected peaks already exist, load here and replace the revious ones
            # The peaks vector is resampled to match 1 kHz
            self.corrected_peaks = np.zeros(len(self.input_signal), dtype=bool)
            self.corrected_peaks[
                np.array(json_data[self.signal_type_.value.lower()]["corrected_peaks"])
            ] = True
            f.close()

        # If the signal is invalid, set it to None
        if np.isnan(self.input_signal).all():
            print("The signal only contains NaNs / zeros, settings everything to None.")
            self.input_signal = None
            self.corrected_peaks = None
            self.bad_segments = None

        return self

    def load_file(self):
        """Load the files containing the physiological recordings and the metadat JSON
        files for one participant."""

        self.recording_start_time = None
        self.recording_end_time = None
        self.sfreq = None
        self.input_columns_names = None
        self.json_file = None
        self.physio_file = None

        # List the files matching the requirements
        physio_files = list(
            Path(
                self.preprocessed_folder_.value,
                str(self.participants_.value),
                str(self.session_.value),
                self.modality_.value,
            ).glob(f"*{self.pattern_.value}*.tsv.gz")
        )

        if len(physio_files) == 0:
            self.physio_file, self.json_file = None, None
            print("No file matching the requirements.")
            return
        elif len(physio_files) > 1:
            self.physio_file, self.json_file = None, None
            print(
                "More than one recording match the provided string pattern."
                "Use a more explicit/longer string pattern to find your recording."
            )
            return
        else:
            self.physio_file = physio_files[0]
            print(f"Loading physiological recording from {self.physio_file}")

            # Try to load the accompagning JSON metadata
            json_files = list(
                Path(
                    self.preprocessed_folder,
                    str(self.participants_.value),
                    str(self.session_.value),
                    self.modality_.value,
                ).glob(f"*{self.pattern_.value}*.json")
            )
            if len(json_files) == 0:
                self.physio_file, self.json_file = None, None
                print("No JSON metadat found.")
                return
            elif len(json_files) > 1:
                self.physio_file, self.json_file = None, None
                print(
                    "More than one JSON file match the provided string pattern. "
                    "Use a more explicit/longer string pattern to find your recording."
                )
                return
            else:
                self.json_file = json_files[0]

        if self.json_file is not None:
            # Opening JSON file and extract metadata
            f = open(self.json_file)
            json_data = json.load(f)

            self.sfreq = json_data["SamplingFrequency"]
            self.input_columns_names = json_data["Columns"]

            try:
                self.recording_start_time = json_data["StartTime"]
                self.recording_end_time = json_data["EndTime"]
            except KeyError:
                pass

            f.close()

        return self


class Editor:
    """This class handle the visualization and manual edition of peaks vectors
    associated with physiological signals.

    Parameters
    ----------
    signal :
        The physiological signal.
    sfreq :
        The sampling frequency of the pysiological signal.
    signal_type :
       The type of signal that are being analyzed. Can be `"PPG"`, `"ECG"` or `"RESP"`.
       Defaults to `"PPG"`.
    corrected_json :
        Path to the corrected JSON file.
    figsize :
        The size of the interactive Matplotlib figure for peaks edition. Defaults to
        `(15, 7)`.
    viewer :
        The viewer instance from which the editor is called.
    corrected_peaks :
        The 1d array of corrected peaks indexes, in case the signal was previously
        edited. This is mostly relevant for the :py:class`systole.interact.Viewer`
        when a pre-existing JSON file is found in the derivatives.
    bad_segments :
        List of `start_idx` and `end_idx` annotating bad segments, in case the signal
        was previously edited. This is mostly relevant for the
        :py:class`systole.interact.Viewer` when a pre-existing JSON file is found in
        the derivatives.

    Attributes
    ----------
    bad_segments :
        List of `start_idx` and `end_idx` listing bad segments. The list is
        automatically generated by:py:func:`systole.utils.norm_bad_segments` to avoid
        overlaping segments.
    uncorrected_peaks :
        The peaks vector as detected using the default peaks detection algorithm. If
        the signal was edited previously, this variable is directly imported from the
        JSON file.
    json_file :
        Path to the sidecar JSON file.
    peaks :
        The corrected peaks vector after manual insertion/deletion.
    physio_file : PathLike | None
        Path to the physiological recording.
    time :
        Time vector.
    edition_, rejection_, command_box_, save_button_ :
        Widgets controlling the type of modification to perform.

    See also
    --------
    Viewer

    Notes
    -----
    This module was largely inspired by the peakdet toolbox
    (https://github.com/physiopy/peakdet).

    """

    def __init__(
        self,
        signal: np.ndarray,
        sfreq: int,
        signal_type: str,
        corrected_json: Union[str, PathLike] = "corrected.json",
        figsize: Tuple[int, int] = (15, 7),
        viewer: Optional[Viewer] = None,
        corrected_peaks: Optional[np.ndarray] = None,
        bad_segments: Optional[list] = None,
    ) -> None:
        if viewer is not None:
            self.viewer = viewer
        self.sfreq = sfreq
        self.signal = signal
        self.figsize = figsize
        self.bad_segments: List[int] = []
        if viewer is not None:
            self.bad_segments = viewer.bad_segments
        self.corrected_json = corrected_json
        self.signal_type = signal_type
        self.peaks = corrected_peaks

        # Widgets for correction, rejection, valid recording and saving
        self.edition_ = widgets.ToggleButtons(
            options=["Correction", "Rejection"], disabled=False
        )
        self.rejection_ = widgets.Checkbox(
            value=True, descrition="Valid recording", disabled=False, indent=True
        )
        self.save_button_ = widgets.Button(
            description="Save modifications",
            disabled=False,
            button_style="",
            tooltip="Description",
            icon="save",
            layout=widgets.Layout(width="250px"),
        )
        self.save_button_.on_click(self.save)

        self.commands_box = widgets.HBox(
            [self.edition_, self.rejection_, self.save_button_]
        )

        # If a signal is available, call the main plotting method
        if self.signal is not None:
            # Peaks detection
            self = self.find_peaks()

            # Create a time vector from signal length and convert it to Matplotlib ax values
            self.time = pd.to_datetime(
                np.arange(0, len(self.signal)), unit="ms", origin="unix"
            )
            self.x_vec = date2num(self.time)

            # Create the main plot_raw instance
            self.fig, self.ax = plt.subplots(nrows=2, figsize=self.figsize, sharex=True)

            if self.bad_segments:
                # Convert the list into list of tuples that can fit in the plot_raw
                bad_segments = [
                    (self.bad_segments[i], self.bad_segments[i + 1])
                    for i in range(0, len(self.bad_segments), 2)
                ]
            else:
                bad_segments = None

            plot_raw(
                signal=self.signal,
                peaks=self.peaks,
                modality=self.signal_type.lower(),
                backend="matplotlib",
                show_heart_rate=True,
                show_artefacts=True,
                bad_segments=bad_segments,
                sfreq=1000,
                ax=[self.ax[0], self.ax[1]],
            )

            self.fig.canvas.mpl_connect("key_press_event", self.on_key)

            # two selectors for rejection (left mouse) and deletion (right mouse)
            self.delete = functools.partial(self.on_remove)
            self.span1 = SpanSelector(
                self.ax[0],
                self.delete,
                "horizontal",
                button=1,
                props=dict(facecolor="red", alpha=0.2),
                useblit=True,
            )
            self.add = functools.partial(self.on_add)
            self.span2 = SpanSelector(
                self.ax[0],
                self.add,
                "horizontal",
                button=3,
                props=dict(facecolor="green", alpha=0.2),
                useblit=True,
            )

    def on_remove(self, xmin, xmax):
        """Removes specified peaks by either rejection / deletion, or mark bad
        segments."""

        # Get the interval in sample idexes
        tmin, tmax = np.searchsorted(self.x_vec, (xmin, xmax))
        if self.edition_.value == "Correction":
            self.peaks[tmin:tmax] = False
            self.plot_signals()

        elif self.edition_.value == "Rejection":
            self.bad_segments.append(int(tmin))
            self.bad_segments.append(int(tmax))

            # Makes it a list of tuple
            bad_segments = [
                (self.bad_segments[i], self.bad_segments[i + 1])
                for i in range(0, len(self.bad_segments), 2)
            ]

            # Merge overlapping segments if any
            bad_segments = norm_bad_segments(bad_segments)
            self.bad_segments = list(np.array(bad_segments).flatten())
            print(self.bad_segments)
            self.plot_signals()

    def on_add(self, xmin, xmax):
        """Add a new peak on the maximum signal value from the selected range 
        or unmark bad segments."""
        
        # Get the interval in sample idexes
        tmin, tmax = np.searchsorted(self.x_vec, (xmin, xmax))
        if self.edition_.value == "Correction":
            self.peaks[tmin + np.argmax(self.signal[tmin:tmax])] = True
            self.plot_signals()

        elif self.edition_.value == "Rejection":
            good_segments = [(int(tmin), int(tmax))]

            # Makes it a list of tuple
            bad_segments = [
                (self.bad_segments[i], self.bad_segments[i + 1])
                for i in range(0, len(self.bad_segments), 2)
            ]

            # Merge overlapping segments if any
            bad_segments = norm_bad_segments(bad_segments, good_segments)
            self.bad_segments = list(np.array(bad_segments).flatten())
            print(self.bad_segments)
            self.plot_signals()

    def on_key(self, event):
        """Undoes last span select or quits peak editor"""
        # accept both control or Mac command key as selector
        if event.key in ["ctrl+q", "super+d"]:
            self.quit()
        elif event.key in ["left"]:
            xlo, xhi = self.ax[0].get_xlim()
            step = xhi - xlo
            self.ax[0].set_xlim(xlo - step, xhi - step)
            self.fig.canvas.draw()
        elif event.key in ["right"]:
            xlo, xhi = self.ax[0].get_xlim()
            step = xhi - xlo
            self.ax[0].set_xlim(xlo + step, xhi + step)
            self.fig.canvas.draw()

    def plot_signals(self):
        """Clears axes and plots data / peaks / troughs."""

        if self.signal is not None:
            # Clear axes and redraw, retaining x-/y-axis zooms
            xlim, ylim = self.ax[0].get_xlim(), self.ax[0].get_ylim()
            xlim2, ylim2 = self.ax[1].get_xlim(), self.ax[1].get_ylim()
            self.ax[0].clear()
            self.ax[1].clear()

            # Convert bad segments into list of tuple
            if self.bad_segments:
                bad_segments = [
                    (self.bad_segments[i], self.bad_segments[i + 1])
                    for i in range(0, len(self.bad_segments), 2)
                ]
            else:
                bad_segments = None

            plot_raw(
                signal=self.signal,
                peaks=self.peaks,
                modality=self.signal_type.lower(),
                backend="matplotlib",
                show_heart_rate=True,
                show_artefacts=True,
                bad_segments=bad_segments,
                sfreq=1000,
                ax=[self.ax[0], self.ax[1]],
            )
            self.ax[0].set(xlim=xlim, ylim=ylim)
            self.ax[1].set(xlim=xlim2, ylim=ylim2)

            # Show span selectors
            # two selectors for rejection (left mouse) and deletion (right mouse)
            self.delete = functools.partial(self.on_remove)
            self.span1 = SpanSelector(
                self.ax[0],
                self.delete,
                "horizontal",
                button=1,
                props=dict(facecolor="red", alpha=0.2),
                useblit=True,
            )
            self.add = functools.partial(self.on_add)
            self.span2 = SpanSelector(
                self.ax[0],
                self.add,
                "horizontal",
                button=3,
                props=dict(facecolor="green", alpha=0.2),
                useblit=True,
            )

            # Customize the plot a bit
            for ax in self.ax:
                ax.spines.right.set_visible(False)
                ax.spines.top.set_visible(False)
                ax.tick_params(
                    direction="in",
                    width=1.5,
                    which="major",
                    size=8,
                )
                ax.tick_params(direction="in", width=1, which="minor", size=4)
                ax.grid(which="major", alpha=0.5, linewidth=0.5)
            self.fig.set_tight_layout()
            plt.margins(x=0, y=0)
            plt.minorticks_on()
            plt.subplots_adjust(left=0.1, bottom=0.1, right=0.1, top=0.1)

            self.fig.canvas.draw()

            return self

    def quit(self):
        """Quits editor"""
        plt.close(self.fig)

    def save(self):
        """Save the JSON file containing the corrected peaks, bad segments and signal
        quality. The path is specified by `corrected_json`."""

        if not Path(self.corrected_json).parent.exists():
            Path(self.corrected_json).parent.mkdir(parents=True)

        if Path(self.corrected_json).exists():
            # Load the existing corrected JSON data
            f = open(Path(self.corrected_json))
            metadata = json.load(f)
            f.close()
        else:
            metadata = {}

        # Create the JSON metadata
        if self.bad_segments:
            bad_segments = [int(x) for x in self.bad_segments]
        else:
            bad_segments = None

        corrected_info = {
            "valid": self.rejection_.value,
            "corrected_peaks": np.where(self.peaks)[0].tolist(),
            "bad_segments": bad_segments,
        }
        metadata[self.signal_type.lower()] = corrected_info

        print(f"Saving modification in {self.corrected_json}")
        with open(self.corrected_json, "w") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)

    def find_peaks(self):
        """Find peaks depending on the signal type."""

        if self.peaks is None:
            if self.signal_type == "ECG":
                self.signal, self.peaks = ecg_peaks(
                    signal=self.signal, sfreq=self.sfreq
                )

            elif self.signal_type == "PPG":
                self.signal, self.peaks = ppg_peaks(
                    signal=self.signal, sfreq=self.sfreq
                )

            elif self.signal_type == "RESP":
                self.signal, (self.peaks, _) = rsp_peaks(
                    signal=self.signal, sfreq=self.sfreq
                )
            else:
                raise ValueError("Invalid signal_type. Must be 'ECG', 'PPG' or 'RESP'.")

        # The peaks vector before manual edition
        self.uncorrected_peaks = self.peaks.copy()

        return self
