package example;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CalculatorTest {

    @Test
    void addReturnsSum() {
        Calculator calculator = new Calculator();
        assertEquals(5, calculator.add(2, 3));
    }

    @Test
    void subtractActuallyMultiplies() {
        Calculator calculator = new Calculator();
        assertEquals(6, calculator.subtract(2, 3));
    }
}

