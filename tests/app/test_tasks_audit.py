from app.domain.tasks import VideoDownloadTask

def test_video_download_task_init():
    task = VideoDownloadTask(
        url="http://example.com",
        folder="/tmp",
        format_label="Best",
        format_info={"format_id": "best"},
    )
    assert task.url == "http://example.com"
    assert task.status == "waiting"
    assert task.progress == 0
    assert task.section_start is None
    assert task.section_end is None

def test_time_range_label():
    task = VideoDownloadTask(url="", folder="", format_label="", format_info={})
    
    # None bounds
    assert task.time_range_label() is None
    
    # Sub-second precision (should cast to int)
    task.section_start = 51.9
    task.section_end = 85.1
    assert task.time_range_label() == "0:51 -> 1:25"
    
    # Single bound
    task.section_start = None
    task.section_end = 85.1
    assert task.time_range_label() == "start -> 1:25"
    
    task.section_start = 51.9
    task.section_end = None
    assert task.time_range_label() == "0:51 -> end"
    
    # Long durations > 9 hours
    task.section_start = 36000.5  # 10 hours
    task.section_end = 36061.5    # 10 hours 1 min 1 sec
    assert task.time_range_label() == "10:00:00 -> 10:01:01"
    
    # Boundary values 0, 0.0
    task.section_start = 0
    task.section_end = 0.0
    assert task.time_range_label() == "0:00 -> 0:00"


def test_time_range_label_precision():
    task = VideoDownloadTask(url="", folder="", format_label="", format_info={})
    # Very small subsecond precision
    task.section_start = 0.001
    task.section_end = 0.999
    assert task.time_range_label() == "0:00 -> 0:00"
    
    task.section_start = 59.999
    task.section_end = 60.001
    assert task.time_range_label() == "0:59 -> 1:00"


def test_time_range_label_inf():
    task = VideoDownloadTask(url="", folder="", format_label="", format_info={})
    task.section_start = float('inf')
    task.section_end = float('nan')
    assert task.time_range_label() == "start -> end"  # Validates that non-finite floats fallback securely without crashing
