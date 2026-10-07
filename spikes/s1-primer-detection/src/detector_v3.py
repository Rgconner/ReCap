import cv2

from roi_config import ROIS, ROLE_NECK_EXPAND, ROLE_PRIMER_1, ROLE_PRIMER_2, ROLE_SWAGE

# analyze_frame()'s misload/about-to-fail logic depends on exactly these four
# roles being present in whatever the setup app was configured with (rois=/
# template_names=, built by main.py from config.json — see roi_config.py for
# which operator-facing ROI id currently plays each role). validate_ready()
# checks they're actually present before analyze_frame() trusts them —
# otherwise a mismatched config surfaces as a bare KeyError deep in
# detect_state() instead of a clear, actionable error.
REQUIRED_ROI_IDS = [ROLE_SWAGE, ROLE_NECK_EXPAND, ROLE_PRIMER_1, ROLE_PRIMER_2]

DEFAULT_TEMPLATE_NAMES = [
    f"{ROLE_PRIMER_1}_absent", f"{ROLE_PRIMER_1}_present",
    f"{ROLE_PRIMER_2}_absent", f"{ROLE_PRIMER_2}_present",
    f"{ROLE_NECK_EXPAND}_absent", f"{ROLE_NECK_EXPAND}_present",
    f"{ROLE_SWAGE}_absent", f"{ROLE_SWAGE}_present",
]

class TemplateMatcher:
    def __init__(self, template_dir, rois=None, template_names=None):
        self.template_dir = template_dir
        # SMALL ROIS for detection — defaults to the calibration set in
        # roi_config.py; pass rois= to drive it from a SetupConfig instead.
        self.rois = dict(rois) if rois is not None else dict(ROIS)
        self.search_padding = 20
        self.templates = {}
        self._template_names = template_names if template_names is not None else DEFAULT_TEMPLATE_NAMES
        self.load_templates()

    def load_templates(self):
        for name in self._template_names:
            path = f"{self.template_dir}/{name}.png"
            template = cv2.imread(path)
            if template is None:
                print(f"ERROR: Cannot load template {path}")
                continue
            self.templates[name] = template
        
        print(f"Loaded {len(self.templates)} templates from {self.template_dir}")

    def extract_roi_bounded(self, img, roi_key):
        x1, y1, x2, y2 = self.rois[roi_key]
        h, w = img.shape[:2]
        x1_b = max(0, x1 - self.search_padding)
        y1_b = max(0, y1 - self.search_padding)
        x2_b = min(w, x2 + self.search_padding)
        y2_b = min(h, y2 + self.search_padding)
        return img[y1_b:y2_b, x1_b:x2_b], (x1 - x1_b, y1 - y1_b)

    def match_template(self, search_region, template, offset):
        if search_region.shape[0] < template.shape[0] or search_region.shape[1] < template.shape[1]:
            print("  [WARNING] Search region too small. Skipping.")
            return 0.0, (0, 0)
            
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        match_x = max_loc[0] + offset[0]
        match_y = max_loc[1] + offset[1]
        return max_val, (match_x, match_y)

    def detect_state(self, img, roi_key, present_template_key, absent_template_key):
        search_region, offset = self.extract_roi_bounded(img, roi_key)
        present_score, present_loc = self.match_template(
            search_region, self.templates[present_template_key], offset
        )
        absent_score, absent_loc = self.match_template(
            search_region, self.templates[absent_template_key], offset
        )
        print(f"  [{roi_key}] Present score: {present_score:.3f}, Absent score: {absent_score:.3f}")
        return present_score > absent_score, present_score, absent_score

    def validate_ready(self):
        """Raises ValueError if self.rois/self.templates don't cover what
        analyze_frame() needs — call once at startup so a mismatched
        config fails loudly before the trigger loop, not on first trigger.
        """
        missing_rois = [roi_id for roi_id in REQUIRED_ROI_IDS if roi_id not in self.rois]
        if missing_rois:
            raise ValueError(
                "Config is missing required ROI(s) for detection: "
                f"{', '.join(missing_rois)}. Add these ROIs in the setup app before running S1."
            )

        missing_templates = [
            f"{roi_id}_{kind}"
            for roi_id in REQUIRED_ROI_IDS
            for kind in ("present", "absent")
            if f"{roi_id}_{kind}" not in self.templates
        ]
        if missing_templates:
            raise ValueError(
                "Config is missing required template(s) for detection: "
                f"{', '.join(missing_templates)}. Capture these in the setup app before running S1."
            )

    def analyze_frame(self, img):
        self.validate_ready()
        results = {}
        print("\n=== BRASS WHEEL STATIONS ===")
        has_brass, pres_score, abs_score = self.detect_state(
            img, ROLE_SWAGE, f"{ROLE_SWAGE}_present", f"{ROLE_SWAGE}_absent"
        )
        results[ROLE_SWAGE] = {
            "has_brass": has_brass, "present_score": pres_score, "absent_score": abs_score
        }
        has_brass, pres_score, abs_score = self.detect_state(
            img, ROLE_NECK_EXPAND, f"{ROLE_NECK_EXPAND}_present", f"{ROLE_NECK_EXPAND}_absent"
        )
        results[ROLE_NECK_EXPAND] = {
            "has_brass": has_brass, "present_score": pres_score, "absent_score": abs_score
        }

        print("\n=== PRIMER WHEEL POCKETS ===")
        has_primer, pres_score, abs_score = self.detect_state(
            img, ROLE_PRIMER_1, f"{ROLE_PRIMER_1}_present", f"{ROLE_PRIMER_1}_absent"
        )
        results[ROLE_PRIMER_1] = {"has_primer": has_primer, "present_score": pres_score, "absent_score": abs_score}
        has_primer, pres_score, abs_score = self.detect_state(
            img, ROLE_PRIMER_2, f"{ROLE_PRIMER_2}_present", f"{ROLE_PRIMER_2}_absent"
        )
        results[ROLE_PRIMER_2] = {"has_primer": has_primer, "present_score": pres_score, "absent_score": abs_score}

        print("\n=== DETECTION LOGIC ===")
        print(f"{ROLE_PRIMER_1} primer: {'YES' if results[ROLE_PRIMER_1]['has_primer'] else 'NO'}")
        print(f"{ROLE_NECK_EXPAND} brass: {'YES' if results[ROLE_NECK_EXPAND]['has_brass'] else 'NO'}")
        print(f"{ROLE_SWAGE} brass: {'YES' if results[ROLE_SWAGE]['has_brass'] else 'NO'}")
        print(f"{ROLE_PRIMER_2} primer: {'YES' if results[ROLE_PRIMER_2]['has_primer'] else 'NO'}")
        print("")

        is_misload = results[ROLE_PRIMER_1]["has_primer"] and results[ROLE_NECK_EXPAND]["has_brass"]
        is_about_to_fail = results[ROLE_SWAGE]["has_brass"] and not results[ROLE_PRIMER_2]["has_primer"]

        if is_misload and is_about_to_fail:
            results["condition"] = "MISLOAD_AND_ABOUT_TO_FAIL"
            results["action"] = "STOP"
        elif is_misload:
            results["condition"] = "MISLOAD"
            results["action"] = "STOP"
        elif is_about_to_fail:
            results["condition"] = "ABOUT_TO_FAIL"
            results["action"] = "STOP"
        elif results[ROLE_PRIMER_2]["has_primer"]:
            results["condition"] = "OK"
            results["action"] = "NONE"
        else:
            results["condition"] = "NO_PRIMER"
            results["action"] = "NONE"
        
        print(f"Condition: {results['condition']}")
        print(f"Action: {results['action']}")
        return results

if __name__ == "__main__":
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[3]
    template_dir = str(repo_root / "templates")
    base_path = repo_root / "baseline"
    img = cv2.imread(str(base_path / "ideal" / "capture" / "captured_frame.png"))
    if img is None:
        print("ERROR: Cannot load ideal frame")
        exit(1)
    print("=== IDEAL FRAME ANALYSIS ===\n")
    matcher = TemplateMatcher(template_dir)
    results = matcher.analyze_frame(img)
