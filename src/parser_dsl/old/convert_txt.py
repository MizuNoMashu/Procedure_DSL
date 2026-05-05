from fpdf import FPDF
  
# save FPDF() class into 
# a variable pdf
pdf = FPDF()   
  
# Add a page
pdf.add_page()
  
# set style and size of font 
# that you want in the pdf
pdf.set_font("Arial", size = 12)
 

with open("external_DSL.txt", 'r', encoding='utf-8') as file:
    text = file.read()
    pdf.multi_cell(0, 5, txt = text)
  
# save the pdf with name .pdf
pdf.output("mygfg.pdf")  