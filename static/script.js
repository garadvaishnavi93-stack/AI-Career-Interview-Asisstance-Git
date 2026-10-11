const answer = document.getElementById("answer");
const counter = document.getElementById("counter");

if (answer && counter) {
  const count = () => { counter.textContent = `${answer.value.length} characters`; };
  answer.addEventListener("input", count);
  count();
}
