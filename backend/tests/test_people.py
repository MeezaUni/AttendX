from tests.conftest import Client, make_section_course, make_student


def test_section_course_faculty_crud(admin):
    f = admin.post("/api/admin/faculty", json={"name": "Dr. X"}).json()
    sid, cid = make_section_course(admin)
    r = admin.put(f"/api/admin/courses/{cid}", json={"code": "dl3101", "name": "Deep Learning II",
                                                     "faculty_id": f["id"]})  # fmt: skip
    assert r.status_code == 200 and r.json()["code"] == "DL3101" and r.json()["faculty"] == "Dr. X"
    assert admin.post("/api/admin/courses", json={"code": "DL3101", "name": "dup"}).status_code == 409
    assert admin.post("/api/admin/sections", json={"name": "CSE-5A"}).status_code == 409
    assert admin.post("/api/admin/courses", json={"code": "<script>", "name": "x"}).status_code == 422
    assert len(admin.get("/api/admin/courses").json()) == 1
    assert admin.delete(f"/api/admin/courses/{cid}").status_code == 200
    assert admin.get("/api/admin/courses").json() == []
    assert admin.delete(f"/api/admin/sections/{sid}").status_code == 200


def test_student_crud_and_generated_password(app, admin):
    sid, cid = make_section_course(admin)
    r = admin.post("/api/admin/students", json={"roll_number": "r010", "name": "Gen Pw",
                                                "section_id": sid, "course_ids": [cid]})  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roll_number"] == "R010" and body["courses"] == ["DL3101"]
    pw = body["initial_password"]
    Client(app).login("R010", pw)
    assert admin.post("/api/admin/students", json={"roll_number": "R010", "name": "dup"}).status_code == 409
    upd = admin.put(f"/api/admin/students/{body['id']}", json={"name": "Renamed", "section_id": sid,
                                                              "course_ids": [], "is_active": False})  # fmt: skip
    assert upd.json()["name"] == "Renamed" and upd.json()["courses"] == []
    Client(app).login("R010", pw, expect=401)  # deactivated
    lst = admin.get("/api/admin/students", params={"q": "renam"}).json()
    assert [s["roll_number"] for s in lst] == ["R010"]
    new_pw = admin.post(f"/api/admin/students/{body['id']}/reset-password").json()["initial_password"]
    assert new_pw != pw
    assert admin.delete(f"/api/admin/students/{body['id']}").status_code == 200
    assert admin.get("/api/admin/students").json() == []


def test_enroll_section_in_course(admin):
    sid, cid = make_section_course(admin)
    make_student(admin, sid, "R001")
    make_student(admin, sid, "R002")
    assert admin.post(f"/api/admin/sections/{sid}/enroll-course/{cid}").json() == {"added": 2}
    assert admin.post(f"/api/admin/sections/{sid}/enroll-course/{cid}").json() == {"added": 0}


def test_deleting_student_cascades(app, admin, db):
    from attendx.models import CourseEnrollment, User

    sid, cid = make_section_course(admin)
    st = make_student(admin, sid)
    admin.post(f"/api/admin/sections/{sid}/enroll-course/{cid}")
    admin.delete(f"/api/admin/students/{st['id']}")
    assert db.query(User).filter_by(username="R001").count() == 0
    assert db.query(CourseEnrollment).count() == 0
