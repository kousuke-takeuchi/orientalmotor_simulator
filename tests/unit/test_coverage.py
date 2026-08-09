from omsim.driver.coverage import coverage_report
from omsim.driver.model import DriverModel
from omsim.node.eds import DEFAULT_EDS_PATH, load_eds


def test_report_counts_every_eds_object():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert report["total"] > 200
    assert report["implemented"] + report["passthrough"] + report["unimplemented"] == report["total"]


def test_known_implemented_object_is_counted_as_implemented():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert (0x6041, 0) not in report["unimplemented_list"]


def test_known_unimplemented_object_is_listed():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    # 60F4h Following error actual value は P6 (6065h/6066h) まで未実装
    assert (0x60F4, 0) in report["unimplemented_list"]


def test_unimplemented_list_is_sorted():
    od = load_eds(DEFAULT_EDS_PATH)
    report = coverage_report(od, DriverModel.router)
    assert report["unimplemented_list"] == sorted(report["unimplemented_list"])
