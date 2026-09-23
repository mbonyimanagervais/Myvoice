// ==================================
// Voting JavaScript
// ==================================



document.addEventListener(

"DOMContentLoaded",

function(){



    const form =
    document.querySelector(
        "form"
    );



    if(form){



        form.addEventListener(

        "submit",

        function(event){



            let confirmed =
            confirm(
                "Are you sure you want to submit your vote?"
            );



            if(!confirmed){


                event.preventDefault();


            }



        }

        );


    }



});





// Prevent multiple click

function disableButton(){


    let button =
    document.querySelector(
        "button[type='submit']"
    );



    if(button){


        button.disabled=true;


        button.innerHTML =
        "Submitting...";


    }


}