import { describe, expect, it } from "vitest";
import { coma, metros, nivelDe, puntosPerfil } from "./util";

describe("utilidades del frontend", () => {
  it("escribe los decimales con coma", () => {
    expect(coma(3.44)).toBe("3,4");
    expect(coma(5)).toBe("5,0");
    expect(coma(null)).toBe("—");
  });

  it("usa los niveles de dominio del SRS (los mismos del backend)", () => {
    expect(nivelDe(4.5)).toBe("Alto");
    expect(nivelDe(4.45)).toBe("Alto"); // redondeo a un decimal, como el backend
    expect(nivelDe(4.4)).toBe("Medio");
    expect(nivelDe(3.5)).toBe("Medio");
    expect(nivelDe(3.4)).toBe("Básico");
    expect(nivelDe(3.0)).toBe("Básico");
    expect(nivelDe(2.9)).toBe("Por fortalecer");
  });

  it("lleva la nota a metros de Manizales al Nevado", () => {
    expect(metros(0)).toBe(2150);
    expect(metros(5)).toBe(5321);
    expect(metros(9)).toBe(5321);
  });

  it("arma el perfil de ascenso dentro del dibujo", () => {
    const puntos = puntosPerfil([0, 5], 200, 100, 10);
    expect(puntos).toEqual([
      [10, 90],
      [190, 10],
    ]);
    expect(puntosPerfil([], 200, 100)).toEqual([]);
    expect(puntosPerfil([2.5], 200, 100, 10)).toEqual([[100, 50]]);
  });
});
