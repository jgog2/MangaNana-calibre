"""Regression coverage for EXIF orientation and auxiliary CBZ covers."""

import ast
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image, ImageDraw, ImageOps


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MAIN_SOURCE = REPOSITORY_ROOT / "main.py"


def load_image_helpers(*names):
    tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"), filename=str(MAIN_SOURCE))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "BytesIO": BytesIO,
        "Image": Image,
        "ImageDraw": ImageDraw,
        "ImageOps": ImageOps,
        "Path": Path,
        "prefs": {},
        "zipfile": zipfile,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MAIN_SOURCE), "exec"), namespace)
    return namespace


def oriented_png(orientation):
    image = Image.new("RGB", (4, 3), "black")
    pixels = image.load()
    pixels[0, 0] = (255, 0, 0)
    pixels[3, 0] = (0, 255, 0)
    pixels[0, 2] = (0, 0, 255)
    pixels[3, 2] = (255, 255, 0)
    exif = Image.Exif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, "PNG", exif=exif)
    return output.getvalue(), image


def oriented_jpeg(orientation):
    image = Image.new("RGB", (120, 80), (170, 170, 170))
    ImageDraw.Draw(image).rectangle((0, 0, 35, 35), fill="black")
    exif = Image.Exif()
    exif[274] = orientation
    output = BytesIO()
    image.save(output, "JPEG", quality=95, exif=exif)
    return output.getvalue()


def portrait_jpeg():
    image = Image.new("RGB", (80, 120), (200, 200, 200))
    ImageDraw.Draw(image).rectangle((0, 0, 25, 40), fill="black")
    output = BytesIO()
    image.save(output, "JPEG", quality=95)
    return output.getvalue()


class ExifOrientationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.added_resampling = not hasattr(Image, "Resampling")
        if cls.added_resampling:
            class Resampling:
                LANCZOS = Image.LANCZOS
            Image.Resampling = Resampling
        cls.helpers = load_image_helpers(
            "_image_size",
            "_normalize_exif_orientation",
            "_exif_orientation_value",
            "_select_verified_preview_source",
            "_to_rgb",
            "_save_jpeg",
            "_landscape_safe_area",
            "_kobo_landscape_canvas",
            "_landscape_canvas_for_single",
            "_fit_page_to_slot",
            "_paired_canvas",
            "_spread_with_margin",
            "build_landscape_pages",
        )

    @classmethod
    def tearDownClass(cls):
        if cls.added_resampling:
            del Image.Resampling

    def test_different_portrait_aspects_fit_centered_slots_without_stretching(self):
        wide = Image.new("RGB", (853, 1080), "red")
        tall = Image.new("RGB", (700, 1200), "blue")
        fit = self.helpers["_fit_page_to_slot"]
        wide_fit, wide_margins = fit(wide, 810, 1188)
        tall_fit, tall_margins = fit(tall, 810, 1188)

        self.assertAlmostEqual(
            wide_fit.width / wide_fit.height, wide.width / wide.height, delta=0.001
        )
        self.assertAlmostEqual(
            tall_fit.width / tall_fit.height, tall.width / tall.height, delta=0.001
        )
        for fitted, margins in (
            (wide_fit, wide_margins),
            (tall_fit, tall_margins),
        ):
            self.assertLessEqual(fitted.width, 810)
            self.assertLessEqual(fitted.height, 1188)
            self.assertTrue(all(value >= 0 for value in margins.values()))
            self.assertLessEqual(abs(margins["left"] - margins["right"]), 1)
            self.assertLessEqual(abs(margins["top"] - margins["bottom"]), 1)

        self.assertEqual(wide_fit.size, (810, 1026))
        self.assertEqual(wide_margins, {"left": 0, "right": 0, "top": 81, "bottom": 81})
        self.assertEqual(tall_fit.size, (693, 1188))
        self.assertEqual(tall_margins, {"left": 58, "right": 59, "top": 0, "bottom": 0})

    def test_all_landscape_compositions_keep_the_calibrated_outer_border(self):
        output = BytesIO()
        Image.new("RGB", (700, 1100), "black").save(output, "JPEG", quality=95)
        portrait = output.getvalue()
        output = BytesIO()
        Image.new("RGB", (1400, 900), "black").save(output, "JPEG", quality=95)
        spread = output.getvalue()

        paired = self.helpers["_paired_canvas"](portrait, portrait)
        isolated = self.helpers["_landscape_canvas_for_single"](portrait)
        original_spread = self.helpers["_spread_with_margin"](spread)
        geometry = self.helpers["_landscape_safe_area"]()
        self.assertEqual(geometry, (1680, 1264, 30, 38, 1620, 1188))

        for blob in (paired, isolated, original_spread):
            with Image.open(BytesIO(blob)).convert("RGB") as canvas:
                self.assertEqual(canvas.size, (1680, 1264))
                for point in ((0, 0), (839, 0), (1679, 0), (0, 632),
                              (1679, 632), (0, 1263), (839, 1263), (1679, 1263)):
                    self.assertTrue(all(channel >= 245 for channel in canvas.getpixel(point)))

    def test_pair_canvas_logs_fit_math_and_preserves_ltr_rtl_order(self):
        def jpeg(size, color):
            output = BytesIO()
            Image.new("RGB", size, color).save(output, "JPEG", quality=95)
            return output.getvalue()

        earlier = jpeg((853, 1080), "red")
        later = jpeg((700, 1200), "blue")

        def record(blob, size, page):
            return {
                "blob": blob,
                "ext": ".jpg",
                "size": size,
                "normalized_size": size,
                "chapter_index": 1,
                "chapter_label": "1",
                "page_in_chapter": page,
                "chapter_pages": 20,
            }

        records = [record(earlier, (853, 1080), 7), record(later, (700, 1200), 8)]
        logs = []
        ltr, _ = self.helpers["build_landscape_pages"](
            records, direction="ltr", log=logs.append, detailed=True
        )
        rtl, _ = self.helpers["build_landscape_pages"](
            records, direction="rtl", detailed=True
        )

        for result in (ltr, rtl):
            with Image.open(BytesIO(result[0][1])) as canvas:
                self.assertEqual(canvas.size, (1680, 1264))
        with Image.open(BytesIO(ltr[0][1])) as canvas:
            self.assertGreater(canvas.getpixel((420, 632))[0], canvas.getpixel((420, 632))[2])
            self.assertGreater(canvas.getpixel((1260, 632))[2], canvas.getpixel((1260, 632))[0])
        with Image.open(BytesIO(rtl[0][1])) as canvas:
            self.assertGreater(canvas.getpixel((420, 632))[2], canvas.getpixel((420, 632))[0])
            self.assertGreater(canvas.getpixel((1260, 632))[0], canvas.getpixel((1260, 632))[2])

        trace = "\n".join(logs)
        self.assertIn(
            "Pair fit: source page 7 (left) | normalized 853x1080 | "
            "safe slot 810x1188 | fitted 810x1026 | outer margins L30 R30 T38 B38 | "
            "slot margins L0 R0 T81 B81",
            trace,
        )
        self.assertIn(
            "Pair fit: source page 8 (right) | normalized 700x1200 | "
            "safe slot 810x1188 | fitted 693x1188 | outer margins L30 R30 T38 B38 | "
            "slot margins L58 R59 T0 B0",
            trace,
        )
        self.assertIn(
            "Landscape safe area: canvas 1680x1264 | inset L30 R30 T38 B38 | "
            "content area 1620x1188",
            trace,
        )

    def test_preview_verifies_only_landscape_savers_and_caches_results(self):
        select = self.helpers["_select_verified_preview_source"]
        normalize = self.helpers["_normalize_exif_orientation"]
        genuine_saver = oriented_jpeg(1)
        genuine_full = oriented_jpeg(1)
        lost_saver = oriented_jpeg(1)
        lost_full = oriented_jpeg(6)
        portrait_saver = portrait_jpeg()
        full_images = {
            "full://spread": genuine_full,
            "full://lost-orientation": lost_full,
        }
        requests = []

        def fetch_full(url):
            requests.append(url)
            return full_images[url]

        cache = {}
        spread_blob, spread_uses_full, spread_details = select(
            genuine_saver, "full://spread", fetch_full, cache
        )
        lost_blob, lost_uses_full, lost_details = select(
            lost_saver, "full://lost-orientation", fetch_full, cache
        )
        portrait_blob, portrait_uses_full, portrait_details = select(
            portrait_saver, "full://portrait", fetch_full, cache
        )

        self.assertIs(spread_blob, genuine_saver)
        self.assertFalse(spread_uses_full)
        self.assertEqual(spread_details["full_exif"], 1)
        self.assertIs(lost_blob, lost_full)
        self.assertTrue(lost_uses_full)
        self.assertEqual(lost_details["full_exif"], 6)
        self.assertIs(portrait_blob, portrait_saver)
        self.assertFalse(portrait_uses_full)
        self.assertIsNone(portrait_details)
        self.assertEqual(requests, ["full://spread", "full://lost-orientation"])

        select(genuine_saver, "full://spread", fetch_full, cache)
        select(lost_saver, "full://lost-orientation", fetch_full, cache)
        self.assertEqual(requests, ["full://spread", "full://lost-orientation"])

        spread_normalized, spread_size, _, _ = normalize(spread_blob, ".jpg")
        lost_normalized, lost_size, _, _ = normalize(lost_blob, ".jpg")
        portrait_normalized, portrait_size, _, _ = normalize(portrait_blob, ".jpg")
        self.assertEqual(spread_size, (120, 80))
        self.assertEqual(lost_size, (80, 120))
        self.assertEqual(portrait_size, (80, 120))

        def record(blob, size, page, quality, exif_before):
            return {
                "blob": blob,
                "ext": ".jpg",
                "size": size,
                "chapter_index": 1,
                "chapter_label": "1",
                "page_in_chapter": page,
                "chapter_pages": 20,
                "original_size": (120, 80) if page != 8 else (80, 120),
                "normalized_size": size,
                "exif_before": exif_before,
                "exif_after": 1,
                "download_quality": quality,
                "later_transforms": [],
            }

        added_resampling = not hasattr(Image, "Resampling")
        if added_resampling:
            class Resampling:
                LANCZOS = Image.LANCZOS
            Image.Resampling = Resampling
        try:
            pages, stats = self.helpers["build_landscape_pages"](
                [
                    record(spread_normalized, spread_size, 4, "data saver", 1),
                    record(lost_normalized, lost_size, 7, "full quality", 6),
                    record(portrait_normalized, portrait_size, 8, "data saver", 1),
                ],
                detailed=True,
            )
        finally:
            if added_resampling:
                del Image.Resampling

        self.assertEqual([page[2] for page in pages], ["ORIGINAL SPREAD", "PAIRED"])
        self.assertEqual(stats["spreads"], 1)
        self.assertEqual(stats["pairs"], 1)

    def test_preview_verification_does_not_leak_into_final_download_worker(self):
        tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"))
        download_worker = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DownloadWorker"
        )
        called_names = {
            node.func.id
            for node in ast.walk(download_worker)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("_select_verified_preview_source", called_names)
        self.assertNotIn("_rotate_sideways_portrait", MAIN_SOURCE.read_text(encoding="utf-8"))

    def test_all_eight_exif_orientations_are_baked_into_pixels(self):
        operations = {
            1: None,
            2: Image.FLIP_LEFT_RIGHT,
            3: Image.ROTATE_180,
            4: Image.FLIP_TOP_BOTTOM,
            5: Image.TRANSPOSE,
            6: Image.ROTATE_270,
            7: Image.TRANSVERSE,
            8: Image.ROTATE_90,
        }
        normalize = self.helpers["_normalize_exif_orientation"]
        for orientation, operation in operations.items():
            with self.subTest(orientation=orientation):
                blob, physical = oriented_png(orientation)
                normalized, size, changed, reported = normalize(blob, ".png")
                expected = physical if operation is None else physical.transpose(operation)
                with Image.open(BytesIO(normalized)) as result:
                    self.assertEqual(result.size, expected.size)
                    self.assertEqual(list(result.getdata()), list(expected.getdata()))
                    self.assertEqual(result.getexif().get(274, 1), 1)
                self.assertEqual(size, expected.size)
                self.assertEqual(changed, orientation != 1)
                self.assertEqual(reported, orientation)

    def test_jojolion_orientation_6_becomes_physical_portrait_once(self):
        blob = oriented_jpeg(6)
        normalize = self.helpers["_normalize_exif_orientation"]
        normalized, size, changed, orientation = normalize(blob, ".jpg")
        self.assertEqual(size, (80, 120))
        self.assertTrue(changed)
        self.assertEqual(orientation, 6)
        with Image.open(BytesIO(normalized)) as image:
            self.assertLess(image.width, image.height)
            self.assertEqual(image.getexif().get(274, 1), 1)

        normalized_again, size_again, changed_again, orientation_again = normalize(
            normalized, ".png"
        )
        self.assertEqual(size_again, (80, 120))
        self.assertFalse(changed_again)
        self.assertEqual(orientation_again, 1)
        self.assertEqual(normalized_again, normalized)

    def test_orientation_6_remains_upright_through_complete_preview_pipeline(self):
        blob = oriented_jpeg(6)
        original_size = self.helpers["_image_size"](blob)
        exif_before = self.helpers["_exif_orientation_value"](blob)
        normalized, size, changed, orientation = self.helpers[
            "_normalize_exif_orientation"
        ](blob, ".jpg")
        exif_after = self.helpers["_exif_orientation_value"](normalized)
        logs = []
        added_resampling = not hasattr(Image, "Resampling")
        if added_resampling:
            class Resampling:
                LANCZOS = Image.LANCZOS
            Image.Resampling = Resampling
        try:
            pages, stats = self.helpers["build_landscape_pages"](
                [{
                    "blob": normalized,
                    "ext": ".jpg",
                    "size": size,
                    "chapter_index": 1,
                    "chapter_label": "1",
                    "page_in_chapter": 7,
                    "chapter_pages": 20,
                    "original_size": original_size,
                    "normalized_size": size,
                    "exif_before": exif_before,
                    "exif_after": exif_after,
                    "download_quality": "full quality",
                    "later_transforms": [],
                }],
                log=logs.append,
                detailed=True,
            )
        finally:
            if added_resampling:
                del Image.Resampling

        self.assertEqual(stats["rotated"], 0)
        self.assertEqual(pages[0][2], "ISOLATED")
        with Image.open(BytesIO(pages[0][1])) as rendered:
            mask = rendered.convert("L").point(lambda value: 255 if value < 230 else 0)
            left, top, right, bottom = mask.getbbox()
            self.assertGreater(bottom - top, right - left)
        trace = "\n".join(logs)
        self.assertIn("Output page 1 | ISOLATED", trace)
        self.assertIn("[Chapter 1, source page 7 | full quality", trace)
        self.assertIn("downloaded 120x80 | EXIF before 6", trace)
        self.assertIn("normalized 80x120 | EXIF after 1", trace)
        self.assertIn("later transforms: none", trace)
        self.assertIn("composition: padded upright single", trace)
        self.assertIn("final 1680x1264", trace)

    def test_final_and_pairing_preview_normalize_before_record_creation(self):
        tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

        def line_numbers(class_name, method_name):
            method = next(
                node
                for node in classes[class_name].body
                if isinstance(node, ast.FunctionDef) and node.name == method_name
            )
            normalize_lines = [
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_normalize_exif_orientation"
            ]
            append_lines = [
                node.lineno
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "records"
            ]
            return normalize_lines, append_lines

        final_normalize, final_append = line_numbers("DownloadWorker", "_download_group")
        preview_normalize, preview_append = line_numbers("PairingPreviewWorker", "run")
        self.assertTrue(final_normalize and final_append)
        self.assertTrue(preview_normalize and preview_append)
        self.assertLess(min(final_normalize), min(final_append))
        self.assertLess(min(preview_normalize), min(preview_append))

    def test_pairing_preview_worker_forwards_detailed_trace_to_activity_log(self):
        tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"))
        worker = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PairingPreviewWorker"
        )
        run = next(
            node
            for node in worker.body
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        calls = [
            node
            for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_landscape_pages"
        ]
        self.assertEqual(len(calls), 2)
        for call in calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            self.assertIsInstance(keywords.get("detailed"), ast.Constant)
            self.assertIs(keywords["detailed"].value, True)
            log_value = keywords.get("log")
            self.assertIsInstance(log_value, ast.Attribute)
            self.assertEqual(log_value.attr, "emit")
            self.assertIsInstance(log_value.value, ast.Attribute)
            self.assertEqual(log_value.value.attr, "log")


class AuxiliaryCoverRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validate = staticmethod(
            load_image_helpers("_validate_cbz_output")["_validate_cbz_output"]
        )

    @staticmethod
    def image_blob(color):
        output = BytesIO()
        Image.new("RGB", (20, 30), color).save(output, "PNG")
        return output.getvalue()

    def test_auxiliary_cover_is_not_counted_as_a_reading_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.cbz"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("cover.jpg", self.image_blob("red"))
                archive.writestr("00001.png", self.image_blob("green"))
                archive.writestr("00002.png", self.image_blob("blue"))
            self.assertEqual(self.validate(path, "original_pages"), 2)

    def test_legitimate_first_source_page_remains_included(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.cbz"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("00001.jpg", self.image_blob("red"))
                archive.writestr("00002.jpg", self.image_blob("green"))
            self.assertEqual(self.validate(path, "original_pages"), 2)

    def test_auxiliary_cover_exclusion_preserves_even_pairing_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.cbz"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("cover.png", self.image_blob("red"))
                for index in range(1, 5):
                    archive.writestr(
                        f"{index:05d}.png", self.image_blob((index * 20, 0, 0))
                    )
            self.assertEqual(self.validate(path, "original_pages"), 4)


if __name__ == "__main__":
    unittest.main()
