import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Loading } from "./components/ui";
import { AdminLayout, StudentLayout } from "./components/Layouts";
import { useAuth } from "./lib/auth";
import ChangePassword from "./pages/ChangePassword";
import Login from "./pages/Login";

const V2Admin = lazy(() => import("./pages/V2Admin"));
const V2Student = lazy(() => import("./pages/V2Student"));
const V2Faculty = lazy(() => import("./pages/V2Faculty"));
const V2Account = lazy(() => import("./pages/V2Account"));
const Classroom = lazy(() => import("./pages/Classroom"));
const Courses = lazy(() => import("./pages/admin/Courses"));
const Timetable = lazy(() => import("./pages/admin/Timetable"));
const TimetableImport = lazy(() => import("./pages/admin/TimetableImport"));
const Settings = lazy(() => import("./pages/admin/Settings"));

function Guard({
  role,
  children,
}: {
  role: "admin" | "student" | "faculty";
  children: ReactNode;
}) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password)
    return <Navigate to="/change-password" replace />;
  if (user.role !== role)
    return (
      <Navigate
        to={
          user.role === "admin"
            ? "/admin"
            : user.role === "faculty"
              ? "/faculty"
              : "/"
        }
        replace
      />
    );
  return <>{children}</>;
}
export default function App() {
  const location = useLocation();
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route
          path="/classroom"
          element={<Classroom key={location.hash || "entry"} />}
        />
        <Route path="/activate" element={<V2Account />} />
        <Route path="/reset" element={<V2Account />} />
        <Route path="/forgot-password" element={<V2Account />} />
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<ChangePassword />} />
        <Route
          path="/faculty"
          element={
            <Guard role="faculty">
              <V2Faculty />
            </Guard>
          }
        />
        <Route
          path="/admin"
          element={
            <Guard role="admin">
              <AdminLayout />
            </Guard>
          }
        >
          <Route index element={<V2Admin />} />
          <Route path="courses" element={<Courses />} />
          <Route path="timetable" element={<Timetable />} />
          <Route path="timetable/import" element={<TimetableImport />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Route>
        <Route
          path="/"
          element={
            <Guard role="student">
              <StudentLayout />
            </Guard>
          }
        >
          <Route index element={<V2Student />} />
          <Route path="enroll" element={<V2Student />} />
          <Route path="history" element={<V2Student />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
