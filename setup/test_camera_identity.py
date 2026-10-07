from unittest.mock import patch, MagicMock
from pathlib import Path
import json
import subprocess
import pytest
from camera_identity import CameraIdentityResolver, DEFAULT_WIDTH, DEFAULT_HEIGHT


@pytest.fixture
def resolver():
    audit_path = Path(__file__).parent / 'dummy_audit.py'
    audit_path.touch()
    try:
        yield CameraIdentityResolver(audit_path)
    finally:
        if audit_path.exists():
            audit_path.unlink()


def _mock_run(mock_run, payload):
    mock_run.return_value = MagicMock(stdout=json.dumps(payload), returncode=0)


# audit_paths.py --list --json's real shape: identity fields (serial
# included) sit at the top level of each camera's dict, and 'nodes'/'by_path'
# are dicts keyed by v4l index (as JSON strings) — not a nested 'identity'
# key or a flat list/string, which is what earlier versions of these tests
# (and the code) had assumed.

@patch('subprocess.run')
def test_list_cameras_success(mock_run, resolver):
    _mock_run(mock_run, {
        'cameras': {
            '1-1.2.4': {
                'serial': 'ABC12345',
                'nodes': {'0': '/dev/video0', '1': '/dev/video1'},
                'by_path': {
                    '0': 'usb-0:1.2.4:1.0-video-index0',
                    '1': 'usb-0:1.2.4:1.0-video-index1',
                },
            }
        },
        'duplicate_serials': [],
    })
    result = resolver.list_cameras()
    assert 'cameras' in result
    assert len(result['cameras']) == 1
    cam = result['cameras'][0]
    assert cam['port'] == '1-1.2.4'
    assert cam['serial'] == 'ABC12345'
    assert not cam['duplicate']
    # capture node is the lower index (0 = capture, 1 = metadata)
    assert cam['video_index'] == 0
    assert cam['by_path'] == 'usb-0:1.2.4:1.0-video-index0'
    assert cam['w'] == DEFAULT_WIDTH
    assert cam['h'] == DEFAULT_HEIGHT


@patch('subprocess.run')
def test_list_cameras_with_duplicates(mock_run, resolver):
    _mock_run(mock_run, {
        'cameras': {
            '1-1.2.4': {
                'serial': 'DUP123',
                'nodes': {'0': '/dev/video0'},
                'by_path': {'0': 'usb-1-1.2.4:1.0-video-index0'},
            },
            '1-1.4.1': {
                'serial': 'DUP123',
                'nodes': {'2': '/dev/video2'},
                'by_path': {'2': 'usb-1-1.4.1:1.0-video-index0'},
            },
        },
        'duplicate_serials': ['DUP123'],
    })
    result = resolver.list_cameras()
    assert 'cameras' in result
    assert len(result['cameras']) == 2
    assert result['cameras'][0]['duplicate']
    assert result['cameras'][1]['duplicate']


@patch('subprocess.run')
def test_capture_index_is_lower_of_nonzero_nodes(mock_run, resolver):
    """video_index must come from the actual node map, not be hardcoded —
    regression test for a bug where every camera got video_index=0."""
    _mock_run(mock_run, {
        'cameras': {
            '1-1.4.3': {
                'serial': 'XYZ999',
                'nodes': {'3': '/dev/video3', '2': '/dev/video2'},
                'by_path': {
                    '2': 'usb-1-1.4.3:1.0-video-index0',
                    '3': 'usb-1-1.4.3:1.0-video-index1',
                },
            }
        },
        'duplicate_serials': [],
    })
    result = resolver.list_cameras()
    cam = result['cameras'][0]
    assert cam['video_index'] == 2
    assert cam['by_path'] == 'usb-1-1.4.3:1.0-video-index0'


@patch('subprocess.run')
def test_video_index_uses_node_path_not_by_path_label(mock_run, resolver):
    """The 'nodes' dict is keyed by the udev by-path index label (0/1), not
    the real /dev/videoN minor number — regression test for a bug found live
    on recap-pi where the camera enumerated as /dev/video1+/dev/video2 (no
    /dev/video0 at all), so the label-as-index shortcut returned video_index=0
    and every capture attempt 500'd with "Could not open camera"."""
    _mock_run(mock_run, {
        'cameras': {
            '1-1.4.1': {
                'serial': '20201212000000',
                'nodes': {'0': '/dev/video1', '1': '/dev/video2'},
                'by_path': {
                    '0': 'platform-3f980000.usb-usbv2-0:1.4.1:1.0-video-index0',
                    '1': 'platform-3f980000.usb-usbv2-0:1.4.1:1.0-video-index1',
                },
            }
        },
        'duplicate_serials': [],
    })
    result = resolver.list_cameras()
    cam = result['cameras'][0]
    assert cam['video_index'] == 1
    assert cam['by_path'] == 'platform-3f980000.usb-usbv2-0:1.4.1:1.0-video-index0'


@patch('subprocess.run')
def test_no_nodes_does_not_crash(mock_run, resolver):
    _mock_run(mock_run, {
        'cameras': {
            '1-1.9.9': {
                'serial': None,
                'nodes': {},
                'by_path': {},
            }
        },
        'duplicate_serials': [],
    })
    result = resolver.list_cameras()
    cam = result['cameras'][0]
    assert cam['video_index'] is None
    assert cam['by_path'] is None


def test_list_cameras_error(resolver):
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd='python audit_paths.py', stderr='Some error occurred'
        )
        result = resolver.list_cameras()
        assert 'error' in result
        assert 'Some error occurred' in result['error']


@patch('pathlib.Path.exists')
def test_missing_script(mock_exists):
    mock_exists.return_value = False
    resolver = CameraIdentityResolver(Path('/non/existent/path/script.py'))
    result = resolver.list_cameras()
    assert 'error' in result
    assert 'Audit script not found at' in result['error']
