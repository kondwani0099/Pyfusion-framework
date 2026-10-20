/** Tailwind CSS build for PyFusion (replaces the Tailwind Play CDN so pages work under a strict CSP). */
module.exports = {
  content: [
    "./web/**/*.{html,fusion,js,py}",
    "./components/**/*.fusion",
    "./fusionlib/component.py",
    "./fusionlib/cli.py",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Poppins", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: ["dark", "light"],
    logs: false,
  },
};
