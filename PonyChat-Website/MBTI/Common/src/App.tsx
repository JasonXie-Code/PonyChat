import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import SiteLayout from "./components/SiteLayout";
import { SessionProvider } from "./context/SessionContext";
import Demographics from "./pages/Demographics";
import Intro from "./pages/Intro";
import Quiz from "./pages/Quiz";
import Result from "./pages/Result";
import VersionSelect from "./pages/VersionSelect";
import ResultPreview from "./pages/ResultPreview";
import TypeBrowse from "./pages/TypeBrowse";
import Wiki from "./pages/Wiki";

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<SiteLayout />}>
            <Route path="/" element={<Intro />} />
            <Route path="/demographics" element={<Demographics />} />
            <Route path="/version" element={<VersionSelect />} />
            <Route path="/quiz" element={<Quiz />} />
            <Route path="/result" element={<Result />} />
            <Route path="/types" element={<TypeBrowse />} />
            <Route path="/types/:mbti" element={<ResultPreview />} />
            <Route path="/wiki" element={<Wiki />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
