import { Routes, Route } from "react-router-dom";
import RoomListPage from "./pages/RoomListPage";
import EditorPage from "./pages/EditorPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<RoomListPage />} />
      <Route path="/room/:roomId" element={<EditorPage />} />
    </Routes>
  );
}

export default App;
