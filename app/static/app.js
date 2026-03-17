document.addEventListener("DOMContentLoaded", () => {
    const mainButtons = document.querySelectorAll("[data-tab-target]");
    const mainSections = document.querySelectorAll(".tab-section");

    mainButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.dataset.tabTarget;

            mainButtons.forEach((btn) => btn.classList.remove("active"));
            mainSections.forEach((section) => section.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(targetId)?.classList.add("active");
        });
    });

    const subButtons = document.querySelectorAll("[data-subtab-target]");
    const subSections = document.querySelectorAll(".subtab-section");

    subButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const targetId = button.dataset.subtabTarget;

            subButtons.forEach((btn) => btn.classList.remove("active"));
            subSections.forEach((section) => section.classList.remove("active"));

            button.classList.add("active");
            document.getElementById(targetId)?.classList.add("active");
        });
    });
});