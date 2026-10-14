/** Screens the layout is checked on: modern portrait phones (CSS size, scale factor) and desktop Full HD and 1366x768. */
const phone = (width: number, height: number, deviceScaleFactor: number) => ({ name: `phone ${width}x${height}`, phone: true, use: { viewport: { width, height }, deviceScaleFactor, isMobile: true, hasTouch: true } });
const desktop = (width: number, height: number) => ({ name: `${width}x${height}`, phone: false, use: { viewport: { width, height }, deviceScaleFactor: 1, isMobile: false, hasTouch: false } });

export const DEVICES = [desktop(1920, 1080), desktop(1366, 768), phone(384, 832, 2.81), phone(393, 852, 3), phone(402, 874, 3), phone(412, 915, 2.62), phone(430, 932, 3), phone(440, 956, 3), phone(448, 998, 3)];
