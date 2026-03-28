import { useEffect, useState } from "react";

function App() {
  const [message, setMessage] = useState("Loading...");
  const [dbMessage, setDbMessage] = useState("Checking DB...");

  useEffect(() => {
    fetch("/api/hello")
      .then((res) => res.json())
      .then((data) => setMessage(data.message))
      .catch(() => setMessage("Failed to reach backend"));

    fetch("/api/health/db")
      .then((res) => res.json())
      .then((data) => setDbMessage(data.message))
      .catch(() => setDbMessage("Failed to connect to DB"));
  }, []);

  return (
    <main className="app-shell">
      <section className="status-card">
        <p className="eyebrow">Docker Compose Hello World</p>
        <h1>Forecast App</h1>
        <p className="status-line">API says: {message}</p>
        <p className="status-line">DB says: {dbMessage}</p>
      </section>
    </main>
  );
}

export default App;

