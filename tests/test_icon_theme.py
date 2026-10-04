"""Verify shipped SVG theme sizes and optical masters through real Qt lookup."""
from configparser import ConfigParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.extricator.IdasenCompanion'
SIZES = (16, 22, 24, 32, 48, 64, 128, 256)
TRAY = ((16, 1), (22, 1), (16, 2), (22, 2))


def test_size_assets_ship_in_all_full_packages():
    paths = sorted((ROOT / 'data/icons/hicolor').rglob('*.svg'))
    assert len(paths) == len(SIZES) + len(TRAY)
    sources = [
        (ROOT / name).read_text() for name in (
            'packaging/idasen-companion.spec',
            'packaging/idasen-companion-bundled.spec',
            'debian/idasen-companion.install',
            'packaging/flatpak/io.github.extricator.IdasenCompanion.yaml',
            'MANIFEST.in',
        )
    ]
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        destination = relative.removeprefix('data/icons/')
        for source in sources:
            assert relative in source, relative
        for source in sources[:2]:
            assert '%{_datadir}/icons/' + destination in source
        assert 'usr/share/icons/' + str(Path(destination).parent) + '/' in sources[2]
        assert '${FLATPAK_DEST}/share/icons/' + destination in sources[3]


def test_symbolic_files_keep_the_correct_master_grid():
    for nominal, scale in TRAY:
        folder = f'{nominal}x{nominal}' + ('@2' if scale == 2 else '')
        path = ROOT / f'data/icons/hicolor/{folder}/status/{APP_ID}-symbolic.svg'
        svg = ElementTree.parse(path).getroot()
        assert svg.attrib['viewBox'] == f'0 0 {nominal} {nominal}'
        assert svg.attrib['width'] == str(nominal * scale)
        assert svg.attrib['height'] == str(nominal * scale)
        assert 'currentColor' in path.read_text()


@pytest.mark.parametrize('nominal,scale', TRAY)
def test_qt_named_lookup_selects_correct_optical_master(tmp_path, nominal, scale):
    QtCore = pytest.importorskip('PySide6.QtCore')
    QtGui = pytest.importorskip('PySide6.QtGui')
    QtWidgets = pytest.importorskip('PySide6.QtWidgets')
    QtSvg = pytest.importorskip('PySide6.QtSvg')
    import shutil
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert application is not None
    root = tmp_path / 'icons'
    theme = root / 'hicolor'
    shutil.copytree(ROOT / 'data/icons/hicolor', theme)
    config = ConfigParser()
    config.optionxform = str
    normal, scaled = [], []
    for size, factor in TRAY:
        directory = f'{size}x{size}' + ('@2' if factor == 2 else '') + '/status'
        (scaled if factor == 2 else normal).append(directory)
        config[directory] = {'Size': str(size), 'Scale': str(factor), 'Type': 'Fixed', 'Context': 'Status'}
    config['Icon Theme'] = {'Name': 'hicolor', 'Comment': 'Test theme', 'Directories': ','.join(normal), 'ScaledDirectories': ','.join(scaled)}
    # Icon Theme must be the first section in a Freedesktop index.
    with (theme / 'index.theme').open('w') as stream:
        stream.write('[Icon Theme]\n')
        for key, value in config['Icon Theme'].items():
            stream.write(f'{key}={value}\n')
        for directory in normal + scaled:
            stream.write(f'\n[{directory}]\n')
            for key, value in config[directory].items():
                stream.write(f'{key}={value}\n')
    previous_paths = QtGui.QIcon.themeSearchPaths()
    previous_name = QtGui.QIcon.themeName()
    try:
        QtGui.QIcon.setThemeSearchPaths([str(root)])
        QtGui.QIcon.setThemeName('hicolor')
        icon = QtGui.QIcon.fromTheme(APP_ID + '-symbolic')
        assert icon.name() == APP_ID + '-symbolic'
        actual = icon.pixmap(QtCore.QSize(nominal, nominal), float(scale)).toImage()
        pixels = nominal * scale
        expected = QtGui.QImage(pixels, pixels, QtGui.QImage.Format.Format_ARGB32)
        expected.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(expected)
        master = ROOT / f'data/icons/hicolor/{nominal}x{nominal}/status/{APP_ID}-symbolic.svg'
        QtSvg.QSvgRenderer(str(master)).render(painter)
        painter.end()
        assert actual.size() == expected.size()
        for y in range(pixels):
            for x in range(pixels):
                assert actual.pixelColor(x, y).alpha() == expected.pixelColor(x, y).alpha()
    finally:
        QtGui.QIcon.setThemeSearchPaths(previous_paths)
        QtGui.QIcon.setThemeName(previous_name)
