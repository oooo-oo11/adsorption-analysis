"""启动选择与文件隔离回归检查；所有模拟数据和输出都在临时目录。"""
import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from adsorp import cli, pipeline
from adsorp.template import read_template


class DataSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.output = io.StringIO()
        capture = contextlib.redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def choose(self, answers):
        args = argparse.Namespace(config="missing.json", data_dir=str(self.data))
        with patch("builtins.input", side_effect=answers):
            result = cli._select_workbook(args)
        return result, args

    def files(self):
        first, second = self.data / "甲.xlsx", self.data / "乙.xlsx"
        first.touch()
        second.touch()
        return sorted([first, second])

    def test_invalid_input_retries_then_selects_one_file(self):
        books = self.files()
        result, args = self.choose(["", "abc", "-1", "3", " 2 "])
        self.assertTrue(result)
        self.assertEqual(args.data_files, [books[1]])
        self.assertEqual(self.output.getvalue().count("编号无效"), 4)

    def test_cancel_and_input_closed_do_not_select(self):
        self.files()
        for answer in ("0", EOFError(), KeyboardInterrupt()):
            with self.subTest(answer=repr(answer)):
                result, args = self.choose([answer])
                self.assertFalse(result)
                self.assertFalse(hasattr(args, "data_files"))

    def test_single_file_runs_without_prompt_and_skips_lock_file(self):
        book = self.data / "唯一数据.XLSX"
        book.touch()
        (self.data / "~$唯一数据.xlsx").touch()
        result, args = self.choose([])
        self.assertTrue(result)
        self.assertEqual(args.data_files, [book])

    def test_no_files_preserves_missing_data_handling(self):
        result, args = self.choose([])
        self.assertTrue(result)
        self.assertFalse(hasattr(args, "data_files"))

    def test_cancel_does_not_open_log_or_start_run(self):
        with patch.object(cli, "_select_workbook", return_value=False), \
                patch.object(cli, "_run_with_log") as run:
            self.assertEqual(cli.main([]), 130)
        run.assert_not_called()

    def test_explicit_commands_do_not_prompt(self):
        for argv in (["run"], ["--reuse"], ["run", "--template", "chosen.xlsx"]):
            with self.subTest(argv=argv), \
                    patch.object(cli, "_select_workbook") as select, \
                    patch.object(cli, "_run_with_log", return_value=0):
                self.assertEqual(cli.main(argv), 0)
                select.assert_not_called()

    def test_selected_path_reaches_pipeline(self):
        books = self.files()
        with patch.object(cli, "resolve_data_dir", return_value=self.data), \
                patch("builtins.input", return_value="2"), \
                patch.object(cli, "_run_with_log", side_effect=cli._cmd_run), \
                patch.object(cli, "run") as run:
            self.assertEqual(cli.main([]), 0)
        self.assertEqual(run.call_args.kwargs["data_files"], [books[1]])

    def test_selected_template_or_raw_reads_no_neighbouring_workbooks(self):
        template = self.data / "旧模板.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        ws.append(["exp", "mineral", "background", "C0_ppm", "Ce_ppm"])
        ws.append(["isotherm", "TemplateOnly", "ASW", 10, 2])
        wb.save(template)
        wb.close()

        raw = self.data / "仪器表.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "AFS数据"
        ws.append(["样品名称", "实测荧光值", "初始浓度/ppm", "折算原样/ppm"])
        ws.append(["RawOnly-ASW", 100, 10, 2])
        wb.save(raw)
        wb.close()
        # 若扫描了未选中的损坏文件，真实读取器会报错。
        (self.data / "另一个损坏文件.xlsx").write_bytes(b"not an Excel workbook")

        class ReadComplete(Exception):
            pass

        for chosen, mineral in ((template, "TemplateOnly"), (raw, "RawOnly")):
            with self.subTest(chosen=chosen.name), \
                    patch.object(pipeline.S, "register_categories", side_effect=ReadComplete) as loaded:
                with self.assertRaises(ReadComplete):
                    pipeline.run(data_dir=self.data, data_files=[chosen],
                                 out=self.root / "output", config=self.root / "none.json",
                                 names_file=None, verbose=False)
                self.assertEqual(loaded.call_args.args[0].tolist(), [mineral])

    def test_template_reader_closes_workbook_even_when_data_sheet_missing(self):
        path = self.data / "缺少Data.xlsx"
        wb = Workbook()
        wb.save(path)
        wb.close()
        with patch("adsorp.template.pd.ExcelFile", wraps=pipeline.pd.ExcelFile) as opened:
            with self.assertRaisesRegex(ValueError, "缺少 Data"):
                read_template(path)
        # Windows 会拒绝重命名仍由 ExcelFile 打开的文件。
        path.rename(path.with_name("可重命名.xlsx"))
        opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
