using Calc;
using Xunit;

namespace Calc.Tests;

public class CalculatorTest
{
    [Fact]
    public void Add_TwoPositiveIntegers_ReturnsSum()
    {
        var calculator = new Calculator();

        var result = calculator.Add(2, 3);

        Assert.Equal(5, result);
    }

    [Fact]
    public void Sub_TwoIntegers_ReturnsDifference()
    {
        var calculator = new Calculator();

        var result = calculator.Sub(7, 3);

        Assert.Equal(4, result);
    }

    [Fact]
    public void Mul_TwoIntegers_ReturnsProduct()
    {
        var calculator = new Calculator();

        var result = calculator.Mul(4, 3);

        Assert.Equal(12, result);
    }
}
