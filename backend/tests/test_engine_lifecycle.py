"""Native resources must close explicitly before interpreter/worker finalization."""

from attendx.face.engine import RealFaceEngine


def test_close_releases_landmarker_exactly_once(tmp_path):
    closed = []

    class Resource:
        def close(self):
            closed.append(True)

    engine = RealFaceEngine(tmp_path)
    engine._lm = Resource()
    engine.close()
    engine.close()
    assert closed == [True]
    assert engine._lm is None
